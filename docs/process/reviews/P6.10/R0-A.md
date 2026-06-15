---
task_id: P6.10
kind: R0-A
stage: impl
surface: docs                # docs-only light track (bilingual README); zero product/dev-harness runtime
reviewer: architect-partner
verdict: clean
cycle: 1
reviewed_branch: origin/claude/P6.10-impl
reviewed_sha: d9ec8050ce44f73c31d540286a8b31a9d8081d31
atoms: [P6.10 (bilingual README — English | 中文 dual-file + reciprocal cross-links)]
adrs_in_play: []            # docs-only, no ADR surface
spine_frozen: n/a           # no code touched — README.md (+2) + README.zh-CN.md (new, +131) only
new_adr: false
gates: n/a                  # docs-only per dispatch (no ruff / mypy / pytest); optional markdown link-sanity run instead
link_sanity: { cross_links: pass (README.md <-> README.zh-CN.md both exist), images: pass (4/4 docs/images/*.png exist), doc_refs: pass (handoff.md, docs/architecture/, docs/decisions/, docs/screenshot.mjs all exist) }
single_lens: true           # light track — translation-fidelity + links + screenshot-reuse; no R0-B / no plan-vs-impl
requires_cross_family_review: false
---

# P6.10 — R0-A (impl stage): bilingual README (English | 中文)

**Verdict: `clean`.** The slice does exactly the dispatched scope and nothing more: README.md gains a 2-line language-toggle header (rest byte-unchanged, PR #65 preserved), and a new README.zh-CN.md is a faithful, structurally one-to-one Chinese translation with every code block / command / path / config filename / screenshot path preserved verbatim. Cross-links are reciprocal and resolve. No code or other files touched. One non-blocking 🟢 nuance in §4 (`fail-closed` rendering) — consistent across both occurrences, English term preserved in-parens, not worth a re-cycle.

## 1. Scope & method

- Reviewed `origin/claude/P6.10-impl` @ `d9ec805` **without checkout** — `git diff origin/main...origin/claude/P6.10-impl` + `git show <sha>:<path>` reads. Shared worktree stayed on `main`.
- Diff surface: **2 files, +133/−0** — `README.md` (+2) modified, `README.zh-CN.md` (+131) added. `git diff --name-status` = `M README.md`, `A README.zh-CN.md`. No scope spill.
- docs-only ⇒ no ruff / mypy / pytest gates per dispatch. Ran the optional markdown link-sanity instead (see §5).

## 2. README.md — English unchanged except the toggle (dispatch point 1) ✅

Full diff is a single hunk at the very top:

```diff
@@ -1,3 +1,5 @@
+**English | [中文](README.zh-CN.md)**
+
 # Orchestrator
```

Exactly two inserted lines (toggle + blank separator) ahead of the `# Orchestrator` H1. **Zero** other hunks ⇒ all prior English body content (PR #65) is byte-identical to `origin/main`. Confirmed.

## 3. README.zh-CN.md — faithful, complete, structurally one-to-one (dispatch points 2 & 3) ✅

Section-by-section parity against the English source (counts machine-verified):

| Structural marker | EN | ZH |
|---|---|---|
| H2 (`##`) | 6 | 6 |
| H3 (`###`) | 10 | 10 |
| `---` rules | 6 | 6 |
| `![](docs/images/…)` | 4 | 4 |
| code fences (```` ``` ````) | 12 | 12 |

Every section present, same order, no omission, no addition:
- intro (tagline + 2 prose paras) → 功能特性 → 安装(环境要求 / 后端 / 前端) → 运行(1 创建首个用户 / 2 启动后端 / 3 启动前端) → 截图(登录页 / 大厅 / 插件管理 / 配置总览) → 设计与开发文档 → 重新生成截图.
- All 8 Features bullets translated 1:1; technical terms preserved verbatim: `seccomp / landlock`, `WAL reader pool`, `session cookie`, `AUTO / COUNTDOWN / HARD`, `DeepSeek` / `Ollama`, `Model Context Protocol`, `E2` / `E3`, agent names (`facilitator`/`skeptic`/`investigator`/`planner`).

**Code blocks / commands / paths preserved byte-for-byte** (only `# comments` translated). Hand-verified each of the 6 blocks, incl. the fragile ones:
- `uv sync --extra api --extra mcp`
- `for f in config/*.example; do cp "$f" "${f%.example}"; done` — shell glob + `${f%.example}` param-expansion intact
- `ORCHESTRATOR_ADMIN_PASSWORD=<password> uv run python -m orchestrator.api.admin create-user <your-username>`
- `uv run python -m orchestrator.api --config config/ --db data/rooms.db` · `127.0.0.1:8000` · `--host / --port`
- `cd ui && npm run dev` · `/rooms /events /plugins /login /logout → :8000`
- `LD_LIBRARY_PATH=/tmp node docs/screenshot.mjs` · `libasound2`
- Config table: all 5 filenames verbatim (`config/llm_providers.yaml`, `llm_models.yaml`, `llm_override.yaml`, `email.yaml`, `web_search.yaml`).
- Screenshots reuse the identical 4 paths (`docs/images/01-login.png` … `04-config.png`); alt-text kept as-is, only the `###` captions translated.
- Doc-link targets verbatim: `handoff.md`, `docs/architecture/` (ADR-001..040), `docs/decisions/`.

## 4. Cross-links reciprocal & correct (dispatch point 4) ✅

- README.md top: `**English | [中文](README.zh-CN.md)**` — current page plain, other linked.
- README.zh-CN.md top: `**[English](README.md) | 中文**` — mirror image, current page plain.
- Bidirectional and reciprocal; both targets exist on-branch (verified §5). Link syntax valid.

🟢 **Non-blocking nuance** — `fail-closed` is rendered as `默认关闭（fail-closed…）` in both the Multi-user-auth bullet and Running §1. `默认关闭` leans "disabled by default" rather than the precise "fails to a secure/closed state", but the English term is kept in-parens **and** paired with `无未认证访问` (no unauthenticated access), so a technical reader recovers the exact concept. Consistent across both occurrences. Not worth a re-cycle for a docs translation; flagging only for the record.

## 5. Link sanity (optional, docs-only) ✅ + dispatch point 5

`git cat-file -e` / `git ls-tree` against `d9ec805` for every referenced path:

- Cross-links: `README.md` ✓, `README.zh-CN.md` ✓
- Images: `docs/images/{01-login,02-lobby,03-plugins,04-config}.png` — 4/4 ✓
- Doc refs: `handoff.md` ✓, `docs/screenshot.mjs` ✓, `docs/architecture/` ✓, `docs/decisions/` ✓

**No code / other files touched** (point 5): `name-status` = exactly `M README.md` + `A README.zh-CN.md`. Confirmed.

## 6. Verdict

`clean` — all 5 dispatched checks pass, link-sanity green, one non-blocking 🟢 nuance with no routing need. Ready for architect Accept + merge.
