/**
 * Playwright screenshot script for Orchestrator GUI.
 *
 * Prerequisites:
 *   1. Backend running:  uv run python -m orchestrator.api --config config/ --db data/rooms.db
 *   2. Frontend running: cd ui && npm run dev
 *   3. A "demo" user exists:
 *        ORCHESTRATOR_ADMIN_PASSWORD=demo123 uv run python -m orchestrator.api.admin create-user demo
 *
 * Usage:
 *   npx playwright install firefox   # once
 *   node docs/screenshot.mjs
 *
 * Screenshots are written to docs/images/.
 */

import { firefox } from "playwright";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const BASE_URL = "http://127.0.0.1:5173";
const OUT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../docs/images"
);
fs.mkdirSync(OUT_DIR, { recursive: true });

const VIEWPORT = { width: 1280, height: 800 };

async function shot(page, name) {
  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file });
  console.log(`  saved: docs/images/${name}.png`);
}

async function main() {
  const browser = await firefox.launch({
    headless: true,
    firefoxUserPrefs: { "network.proxy.type": 0 },
  });
  const ctx = await browser.newContext({ viewport: VIEWPORT });
  const page = await ctx.newPage();

  // 1. Login page
  console.log("1. Login page");
  await page.goto(BASE_URL, { waitUntil: "commit" });
  await shot(page, "01-login");

  // 2. Login
  console.log("2. Logging in...");
  await page.fill('[data-testid="login-userid"]', "demo");
  await page.fill('[data-testid="login-password"]', "demo123");
  await page.click('[data-testid="login-submit"]');
  await page.waitForTimeout(1500);

  // 3. Lobby (room create + room picker)
  console.log("3. Lobby / room picker");
  await shot(page, "02-lobby");

  // 4. Plugins page
  console.log("4. Plugins page");
  await page.click('button:has-text("插件")');
  await page.waitForTimeout(800);
  await shot(page, "03-plugins");

  // 5. Config page
  console.log("5. Config page");
  await page.click('button:has-text("配置")');
  await page.waitForTimeout(800);
  await shot(page, "04-config");

  // 6. Room view — go back to lobby and try to enter a room
  console.log("6. Room view");
  await page.click('button:has-text("聊天")');
  await page.waitForTimeout(500);
  const roomItem = page.locator('[data-testid^="room-item"]').first();
  if (await roomItem.isVisible({ timeout: 2000 }).catch(() => false)) {
    await roomItem.click();
    await page.waitForTimeout(1000);
    await shot(page, "05-room-view");
  } else {
    console.log("   (no rooms yet; screenshotting lobby empty state)");
    await shot(page, "05-room-view");
  }

  await browser.close();
  console.log("\nDone. Screenshots saved to docs/images/");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
