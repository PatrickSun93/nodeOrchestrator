import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";

// Constitutional tests (ADR-026 D4, HR#2):
// Verify structural guarantees: binds-API-only (no fetch/WebSocket outside src/api/),
// no DB/fs runtime deps in package.json.

const SRC_DIR = path.resolve(import.meta.dirname, ".");
const API_DIR = path.resolve(SRC_DIR, "api");

function readSourceFiles(dir: string, excludeDir?: string): { file: string; content: string }[] {
  const results: { file: string; content: string }[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (excludeDir && fullPath === excludeDir) continue;
      results.push(...readSourceFiles(fullPath, excludeDir));
    } else if (
      entry.isFile() &&
      /\.(ts|tsx)$/.test(entry.name) &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".test.tsx")
    ) {
      results.push({ file: fullPath, content: fs.readFileSync(fullPath, "utf-8") });
    }
  }
  return results;
}

describe("constitutional: binds-API-only (HR#2)", () => {
  it("no source file outside src/api/ directly calls fetch or new WebSocket", () => {
    const nonApiFiles = readSourceFiles(SRC_DIR, API_DIR);

    const violations: string[] = [];
    for (const { file, content } of nonApiFiles) {
      // Detect bare fetch() calls (not in comments or strings naively)
      // Use regex to find function call patterns
      if (/\bfetch\s*\(/.test(content)) {
        violations.push(`${path.relative(SRC_DIR, file)}: uses fetch() directly`);
      }
      if (/\bnew\s+WebSocket\s*\(/.test(content)) {
        violations.push(`${path.relative(SRC_DIR, file)}: uses new WebSocket() directly`);
      }
    }
    expect(violations, `These files violate binds-API-only: ${violations.join(", ")}`).toHaveLength(
      0,
    );
  });

  it("no source file imports orchestrator Python paths", () => {
    const allFiles = readSourceFiles(SRC_DIR);
    const violations: string[] = [];
    for (const { file, content } of allFiles) {
      if (/from\s+['"].*orchestrator.*['"]/.test(content)) {
        violations.push(path.relative(SRC_DIR, file));
      }
    }
    expect(violations, `Files import orchestrator: ${violations.join(", ")}`).toHaveLength(0);
  });

  it("package.json has no DB/sqlite/filesystem runtime dependency", () => {
    const pkgPath = path.resolve(SRC_DIR, "../package.json");
    const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf-8")) as {
      dependencies?: Record<string, string>;
    };
    const deps = Object.keys(pkg.dependencies ?? {});
    const DB_PATTERNS = [
      "sqlite",
      "better-sqlite",
      "sequelize",
      "typeorm",
      "prisma",
      "knex",
      "pg",
      "mysql",
      "mongodb",
    ];
    for (const dep of deps) {
      for (const pattern of DB_PATTERNS) {
        expect(
          dep,
          `package.json runtime dep "${dep}" matches DB pattern "${pattern}"`,
        ).not.toContain(pattern);
      }
    }
  });
});
