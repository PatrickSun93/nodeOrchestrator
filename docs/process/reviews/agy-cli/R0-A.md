---
artifact: R0-A review
subject: agy-cli (Antigravity CLI) LLM provider — externally authored
branch: origin/claude/agy-cli-provider
commit: 4628781
base: 626c6a2 (round-1 reviewed commit)
round: 2 (re-review; supersedes round-1 blocking)
reviewer_role: architect-partner (manual dispatch, non-standard slice)
verdict: clean
date: 2026-06-11
gates:
  ruff: pass        # All checks passed!
  mypy: pass        # files=src,tests — Success, no issues in 309 source files
  pytest: pass      # 2510 passed (2460 baseline + 50 new agy: parser 21 + provider 29)
supersedes: round-1 R0-A @ 626c6a2 (verdict blocking)
summary: >
  Every round-1 blocking defect is fixed and independently re-verified
  against the resolved types: B1 default_temperature removed, B2/B3 field
  + type corrected, B4 system str|None guarded, B5 ruff clean, B6 two test
  files added (50 tests, asyncio_mode=auto so they truly run), Y1 multi-turn
  stdin preserved, Y2 subprocess lifecycle (kill-on-timeout + CancelledError
  re-raise + OSError-on-launch) ported faithfully from the reference. All
  three gates run green in an isolated worktree. Spine remains clean — no
  spine file in the diff, zero LLMPurpose reference in agy source, purposes.py
  untouched. No routing / scope / constitutional / new-ADR decision implicated.
  Mergeable.
---

# R0-A (round 2) — agy-cli LLM provider (external) @ 4628781

**Scope re-reviewed:** the fix commit `4628781` on top of the round-1
external commit `626c6a2`. Fix diff = `agy_cli.py` + `agy_cli_output.py`
parser + `config/llm_providers.yaml.example` + ADR-002 "Implemented" note +
`config_loader.py` import-sort + `test_config_loader.py` count bump + two new
test files. Full branch vs `origin/main`: +1007 / −3, 10 files.

**Method:** read-only on the shared tree (`git show` / `git diff
626c6a2..` for the fix, `origin/main...` for the full change); gates run in
an isolated detached worktree @ `4628781` with `uv sync --all-extras`.
Reference baseline throughout: `claude_code_cli` provider + its two test files.

**Verdict: `clean`.** Bounces from round-1 `blocking`. All eight tracked
defects (B1–B6, Y1, Y2) verified fixed; gates empirically green; spine
re-confirmed untouched.

---

## Gate results (empirical — isolated worktree @ 4628781)

| Gate | Round 1 | Round 2 | Detail |
|---|---|---|---|
| **ruff** | ❌ 6 errors | ✅ **pass** | `All checks passed!` — I001 / F401 / F841 / E501×2 / UP041 all gone. |
| **mypy** (`files=src,tests`) | ❌ 5 errors | ✅ **pass** | `Success: no issues found in 309 source files` (+2 = new test files). |
| **pytest** | ✅ 2460 (agy = 0) | ✅ **pass** | **2510 passed** (exit 0). +50 agy tests: parser 21 + provider 29. |

`asyncio_mode = "auto"` (`pyproject.toml:47`) confirmed — the bare `async def`
provider tests genuinely execute (not silently skipped); the agy-only run shows
50/50 green.

---

## Round-1 blocking items — verification

| # | Round-1 finding | Status | Evidence @ 4628781 |
|---|---|---|---|
| **B1** | `model.default_temperature` (attr doesn't exist; `AttributeError` on common path) | ✅ fixed | The `elif model.default_temperature …` branch is **deleted**; `--temperature` now flows only from `request.temperature is not None`. Guarded by `test_no_temperature_when_not_set`. |
| **B2** | `request.id` → `AttributeError` every call | ✅ fixed | `request_id=request.request_id` (agy_cli.py call into parser). Implicitly exercised by every happy-path test (an LLMResponse cannot return otherwise). |
| **B3** | `model_id_used=model.provider_model_id` (wrong field + `str`→`ModelId` type error) | ✅ fixed | `model_id_used=model.id`. Guarded by `test_model_id_used_is_model_id` (asserts `ModelId("agy_gemini_flash")`, not the wire id). |
| **B4** | `"\n\n".join(request.system)` — crashes on `None`, char-splices a `str` | ✅ fixed | `system_text = request.system or ""` + `if system_text:` guard, emitting `[System]\n{…}` exactly like the reference. Guarded by `test_system_none_handled` + `test_system_str_sent_as_block` (latter explicitly asserts no character-splitting). |
| **B5** | ruff red (I001, `Capability` F401, `assistant_text` F841, E501×2, UP041) | ✅ fixed | `Capability` import dropped; import order corrected (`agy_cli` before `claude_code_cli`); `assistant_text` gone (folded into B-Y1 fix); parser comprehension wrapped; `except (TimeoutError, asyncio.CancelledError)`. ruff green. |
| **B6** | zero tests | ✅ fixed | `test_agy_cli_provider.py` (29) + `test_agy_cli_output_parser.py` (21). Coverage detail below. |
| **Y1** | multi-turn stdin — assistant turns dropped (the `assistant_text` F841 fingerprint) | ✅ fixed | `for msg in request.messages: prompt_parts.append(f"[{msg.role.title()}]\n{msg.content}")` — all roles preserved with labels, matching the reference. Guarded by `test_all_messages_in_stdin` (user + assistant + user). |
| **Y2** | subprocess lifecycle — no kill-on-timeout, no `CancelledError`, no `OSError`-on-launch | ✅ fixed | Now a **line-faithful port** of the reference: `except (TimeoutError, asyncio.CancelledError)` → `process.kill(); await process.wait()` (swallowing `ProcessLookupError`/`OSError`), re-raise on cancellation else `TransientProviderError`; spawn wrapped with `except OSError → ProviderUnhealthyError`. Guarded by `test_timeout_kills_subprocess`, `test_cancellation_kills_subprocess_and_propagates`, `test_kill_failure_does_not_mask_timeout`, `test_oserror_raises_unhealthy`. |

G3 (round-1 nit: stray `" ; "` in the `ToolsNotSupportedError` message) is also
fixed → `"(request had N tool(s))"`.

---

## New test coverage (B6) — assessment vs the dispatch checklist

Architect's requested coverage was: error classification, `health_check`,
timeout, system None/str, parser malformed input. All present:

- **Error classification** — `FileNotFoundError`/`OSError` → `ProviderUnhealthyError`;
  non-zero exit with rate-limit / `503` marker → `TransientProviderError`; non-zero
  without marker → `PermanentProviderError`. ✅
- **`health_check`** — unknown binary → False; `--version` rc 0 → True; rc≠0 → False;
  `subprocess.TimeoutExpired` → False. ✅
- **timeout** — `TransientProviderError` raised **and** child killed; kill-failure
  doesn't mask the timeout; cancellation kills + re-propagates `CancelledError`. ✅
- **system None / str** — both branches asserted, including the no-character-split guard. ✅
- **parser malformed input** — non-JSON, top-level array, top-level string, malformed
  `tool_call` (empty name → `ValidationError`→`PermanentProviderError`); plus content-as-list
  flattening, non-text-block skip, non-str coercion, missing content/usage defaults,
  every `_STOP_REASON_MAP` branch + unknown→`stop` + non-str→`stop`. ✅

Also covers the security boundary the round-1 review praised: `base_url`
allowlist (`ConfigError` on untrusted / empty allowlist) and `AGY_BASE_URL`
parent-env stripping (unit + through-`call()` env assertion). The tests double as
explicit regression guards for B1/B3/B4/Y1/Y2 — the single happy-path assertion
that round-1 said "would have caught B1/B2" is now present and green.

---

## Spine / constitutional — re-confirmed CLEAN

- **No spine file in the diff.** `git diff --name-only origin/main...4628781` filtered
  for `purposes.py | autonomy/gate | _execute_local_call | countdown | run_pipeline | core/`
  → **none**. The autonomy gate, `_execute_local_call`, the COUNTDOWN spine and
  `run_pipeline` are byte-untouched.
- **No new `LLMPurpose`.** agy source (provider + parser) contains zero `LLMPurpose`
  references; `purposes.py` diff is empty. (The test file imports the pre-existing
  `LLMPurpose.AGENT_RESPONSE` only to build a request fixture — not a new surface.)
- **Routing untouched.** `can_use_orchestrator_tools() → False` (now carries a
  "structural property … do not override" comment matching the ADR-003 precedent) and
  `call()` rejects tool-bearing requests with `ToolsNotSupportedError`. agy cannot become
  a tool-execution / autonomy surface; no α/β/γ re-routing introduced.
- **ADR-002** received an additive "2026-06-11 (agy-cli-provider) — Implemented" note
  registering `ProviderType.AGY_CLI` under the existing "new type = new module + registry
  entry" contract and inscribing the no-tools structural stance. Additive, non-spine.

---

## Remaining non-blocking observations (dispositioned, not gating)

- **Y3 (parser tool-call `arguments` shape)** — the parser still hands
  `function.arguments` straight to `ToolCall.arguments: dict`. Real OpenAI wire format
  encodes it as a JSON **string**, which would `ValidationError`→`PermanentProviderError`.
  This branch is **dead** in normal operation (tools are rejected upstream;
  `can_use_orchestrator_tools()→False`) and is now *safe* (the construction is wrapped in
  `try/except ValidationError`). Acceptable to ship as-is; if agy ever grows tool support
  this branch needs a JSON-string decode. Non-blocking.
- **G1 (no effort plumbing)** — agy drops `request.effort_level` (no `--effort`), unlike the
  reference's `Capability.EFFORT` mapping. Plausibly correct for Gemini; the dropped
  `Capability` import (B5) is consistent with this stance. Non-blocking.
- **G2 (`time.monotonic` vs reference `time.perf_counter`)** — both fine for latency.
  Cosmetic divergence only.

These were all ≤🟡 in round 1 and none block merge; flagged here only for the record.

---

## Bottom line

`4628781` resolves the full round-1 must-fix checklist with empirical gate
evidence and a test suite at parity with `claude_code_cli`. Spine and routing
are clean; the change is a pure additive content-gen provider within the
established ADR-002/003 pattern, correctly carrying an ADR-002 amendment note
and a config-example entry. **Verdict: clean — mergeable.** No architect
decision is implicated (no routing/scope/constitutional/new-ADR surface); the
only open items are the three non-blocking observations above, none gating.
