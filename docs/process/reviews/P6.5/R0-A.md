---
task_id: P6.5
kind: R0-A-on-impl
surface: product
stage: impl
cycle: 2
reviewed_ref: origin/claude/P6.5-impl @ 3ae8042
supersedes: R0-A cycle-1 (@ fb68efc, verdict needs_architect) — this re-review covers the α-bundle rework
lens: subprocess-injection threat-probe (cross-family dual-lens; absorbs the R0-B R1/R2 fix this cycle)
verdict: clean   # all cycle-1 + cross-family findings resolved with fail-on-revert coverage; G1 unregressed; spine 0-diff; gates green; ready to merge
author: architect-partner
---

# P6.5 R0-A (cycle 2) — git_push remote hardening: α-bundle rework re-review

## TL;DR

The cycle-2 α bundle resolves **all five** routed findings (R0-B R1🔴 + R2🟡 refspec bypass; R0-A Y1/Y2🟡 test-honesty; Y3🟡 annotation). The cycle-2 diff (`88ac9bd..3ae8042`) is **+5 product lines / +71 test lines / ±2 ADR lines**, touches only `subprocess_tools.py` + its test + ADR-036, and is **purely additive** to G1 — no regression, **spine 0-diff**, no new `LLMPurpose`, ADR-037 D2 isolation contract untouched. I re-ran the full gate independently in an isolated detached worktree (`uv sync --all-extras`): **ruff clean / mypy 310 files / pytest 2527 passed**. Beyond passing, I confirmed each new guard genuinely **bites** with three fail-on-revert probes (remove the guard → the test fails). **Verdict: clean — ready to merge.**

## Cycle-1 → cycle-2 resolution

| # | Cycle-1 finding | Fix in 3ae8042 | Independently verified |
|---|---|---|---|
| **R0B-R1** 🔴 | `branch=":main"` deletes the remote ref, evading the `--delete` ban | `if branch.startswith(":") or branch.startswith("+"): raise LocalToolError(... "only plain branch names are accepted")`, placed before argv build **and** before the posture branch (guards both `_sandbox_dispatch` and the non-sandbox `_dispatch` RCE path) | code-read + **PROBE A** (remove guard → `test_git_push_refspec_delete_rejected` fails); the test also asserts the remote `main` ref survives via `git ls-remote` |
| **R0B-R2** 🟡 | `branch="+main:main"` force-pushes, evading `--force` | same `:`/`+` guard | **PROBE A** (`test_git_push_refspec_force_push_rejected` fails on revert) |
| **R0A-Y1** 🟡 | happy-path passed on a *failed* push; the load-bearing `file`-allowlist choice was unguarded | happy-path now `git init -b main` + asserts `exit_code=0`; new `test_git_push_transport_allowlist_set` pins the set (`file` in, `ext` out) | **PROBE B** (drop `file` from the allowlist → both tests fail) |
| **R0A-Y2** 🟡 | the `ext::` test was a false-pass (side-effect that never fires) | asserts `"not allowed" in result.content` (the protocol-denied signal) | **PROBE C** (re-allow `ext::` on the push env → test fails) |
| **R0A-Y3** 🟡 | ADR-036 note overstated "operator-configured" | "operator-configured" → "configured" + explicit `apply_edit`/`.git/config` config-poisoning caveat + → task #109 | ADR diff read; matches the routed wording + deferral |

## Independent verification

**Refspec guard (R1/R2) — placement + completeness.** The new 5-line block sits in `_make_git_push._impl` between the existing flag-shape (`startswith("-")`) check and the banned-flags loop — i.e. **before the argv build and before the `if posture_resolver is not None` branch**, so it covers both dispatch paths exactly as the existing flag-shape guard does. It closes the two destructive refspec spellings R0-B named (`:dst` = delete, `+src:dst` = force); a non-prefixed mapping (`a:b`) is a normal fast-forward push still gated by the configured-remote check + the always-HARD confirm, and a HEAD-resolved branch is a plain name. Fail-fast: a `:main` is rejected before the `git remote` subprocess even spawns. (PROBE A: with the guard removed, both refspec tests fail — the delete test because the `:main` push then actually deletes the bare remote's `main`, so both the `pytest.raises` and the `ls-remote`-intact assertion fall over.)

**G1 no regression.** The cycle-2 change is additive only. The configured-remote restriction (`remote not in configured_remotes` → reject, fail-closed on `git remote` error/timeout → `set()`) and the `GIT_ALLOW_PROTOCOL` overlay on all four git invocations (HEAD resolve, `git remote` list, push, `git remote get-url`) are untouched. All 18 `git_push` test nodes are green, including the pre-existing flag-shape / banned-flag / inline-URL / ext-transport-name guards.

**Spine byte-frozen.** `git diff main..3ae8042` is **empty** across `src/orchestrator/autonomy/`, `core/`, `llm/`; the only `src/` file changed is `subprocess_tools.py`. `_execute_local_call` (`tools/executor.py`), `scoring.py`, the gate, and `autonomy/` are 0-diff. No new `LLMPurpose` (argv stays fixed `["git","push",remote,branch]`; t9/t12 reasoning holds by inspection). ADR-037 D2 isolation contract untouched — `_sandbox_dispatch` signature unchanged; the guard lives entirely above the executor inside `_make_git_push._impl`.

**Gates (isolated detached worktree @ 3ae8042, `uv sync --all-extras`).**
- `ruff check .` → **All checks passed**
- `mypy` (strict, `files=[src,tests]`) → **Success: no issues found in 310 source files**
- `pytest` (full) → **2527 passed** (1 pre-existing Starlette deprecation warning, unrelated)

**Fail-on-revert probes (the "真咬" check).** In the throwaway worktree I reverted each guard in turn, ran the affected tests, and restored (`git checkout`) — confirming none of the cycle-2 tests are vacuous:
- **PROBE A** — remove the `:`/`+` guard → `refspec_delete` + `refspec_force` → **2 failed**
- **PROBE B** — drop `file` from `_GIT_ALLOW_PROTOCOL` → `transport_allowlist_set` + `happy_path_local_remote` → **2 failed**
- **PROBE C** — re-allow `ext::` on the push env → `ext_protocol_blocked_by_allowlist` → **1 failed**

## Cross-family note (R0-B)

R0-B's R1/R2 were folded into this α bundle, and I confirmed them under the **same subprocess-injection / attacker-perspective lens** R0-B used — PROBE A is an attacker-perspective fail-on-revert. The fix is surgical and bites. Whether to also re-run a separate R0-B session for cycle-2 is your dispatch call (`dual-lens-r0b.md`); from the R0-A lens the cross-family findings are resolved.

## Verdict

**`clean`.** All five routed findings are resolved with real fail-on-revert coverage; G1 is unregressed; spine 0-diff; gates green. No open finding and no architect decision on the review axis — Y3's config-poisoning follow-on was already routed → task #109. The slice is ready to merge → P6.5 closes.
