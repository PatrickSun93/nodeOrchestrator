---
artifact: R0-A review
subject: agy-cli (Antigravity CLI) LLM provider — externally authored
branch: origin/claude/agy-cli-provider
commit: 626c6a2
reviewer_role: architect-partner (manual dispatch, non-standard slice)
verdict: blocking
date: 2026-06-11
gates:
  ruff: fail        # 6 errors
  mypy: fail        # 5 errors (files=src,tests, 307 files checked)
  pytest: pass      # 2460 passed — existing suite unaffected; agy has zero tests
summary: >
  Constitutional/spine impact is CLEAN and the subprocess-security pattern is
  faithfully ported from claude_code_cli. But the provider fails 2 of 3 static
  gates and carries three first-invocation-fatal runtime bugs, with zero tests.
  Not mergeable as-is. No routing/scope/constitutional/new-ADR decision is
  implicated — every finding is a within-surface defect with a mechanical fix.
---

# R0-A — agy-cli LLM provider (external) @ 626c6a2

**Scope reviewed:** 5 files, +291 / −0 vs `origin/main`.
`types.py` (`ProviderType.AGY_CLI`), `providers/agy_cli.py` (new `AgyCliProvider`),
`parsers/agy_cli_output.py` (new parser), `config_loader.py` + `providers/__init__.py`
(registration).

**Method:** read-only on shared tree (`git show` / `git diff origin/main...`);
gates run in an isolated detached worktree @ 626c6a2 with `uv sync --all-extras`.

**Verdict: `blocking`.** Spine clean; security pattern good; but gates red + three
fatal runtime bugs + no tests. Bounce to author for must-fixes, then re-review.

---

## Gate results (empirical)

| Gate | Result | Detail |
|---|---|---|
| **ruff** | ❌ FAIL | 6 errors: `I001` (config_loader import unsorted — `agy_cli` must precede `claude_code_cli`), `F401` (`Capability` imported-unused), `F841` (`assistant_text` assigned-unused), `E501` ×2 (agy_cli_output.py:63, agy_cli.py:119), `UP041` (`asyncio.TimeoutError`→`TimeoutError`). 3 auto-fixable. |
| **mypy** (`files=src,tests`, 307 files) | ❌ FAIL | 5 errors, all `agy_cli.py`: `default_temperature` attr ×2 (L114-115), `system` join arg-type (L117), `request.id` attr (L165), `model_id_used` arg-type (L167). |
| **pytest** | ✅ PASS | 2460 passed. Existing suite unaffected by the registration import — but **only because nothing exercises agy** (zero agy tests). The runtime bugs below are entirely latent. |

---

## Findings by review focus

### Focus 1 — Constitutional / spine: ✅ CLEAN

Zero spine impact, confirmed by reading all 5 files:

- Does **not** touch the autonomy gate, `_execute_local_call`, the COUNTDOWN spine,
  or `run_pipeline`. Pure content-gen provider.
- **No new `LLMPurpose`** — neither provider nor parser references `LLMPurpose`;
  routing is untouched. (No α/β/γ re-routing surface introduced.)
- `ProviderType.AGY_CLI` is an **additive** member of the ADR-002 provider set,
  enumerated exactly like `CLAUDE_CODE_CLI` / `OPENAI_COMPATIBLE` / `MOCK`. The
  `PROVIDER_TYPE_REGISTRY` entry follows the documented "new type = new module +
  registry entry" contract.
- `can_use_orchestrator_tools()` returns `False` and `call()` rejects tool-bearing
  requests with `ToolsNotSupportedError` → cannot become a tool-execution / autonomy
  surface. Correct, mirrors ADR-003 precedent.
- **No ADR required** (additive content-gen provider within established ADR-002/003
  pattern). Author correctly added none.

### Focus 2 — Provider-pattern consistency vs `claude_code_cli`

The interface *shape* is correct: dataclass `provider_id` field, `can_use_orchestrator_tools`,
sync `health_check` (faithfully mirrors the reference, including the PATH/abs-path guard),
async `call()` — structurally satisfies the `LLMProvider` protocol. But the request→argv
translation references three fields that **do not exist on the resolved types**:

- 🔴 **B1 — `model.default_temperature` (agy_cli.py:114-115).** `ModelProfile` has no
  `default_temperature` field (it has `default_effort`). On the common path
  (`request.temperature is None`) this raises `AttributeError`. mypy: `attr-defined` ×2.

- 🔴 **B2 — `request.id` (agy_cli.py:165).** `LLMRequest` exposes `request_id`, not `id`.
  Raises `AttributeError` on **every** call. Reference uses `request.request_id`. mypy:
  `attr-defined`.

- 🔴 **B3 — `model_id_used=model.provider_model_id` (agy_cli.py:167).** Semantically wrong
  *and* a type error: `model_id_used` must be the internal `ModelId` (`model.id`), not the
  provider wire id (`provider_model_id: str`). Reference passes `model.id`. mypy: `arg-type`
  (`str` vs `ModelId`).

- 🟡 **Y2 — subprocess lifecycle gaps vs reference.** `call()` on timeout raises
  `TransientProviderError` **without** `proc.kill()` / `await proc.wait()` → orphaned child
  leak. It also (a) does not handle `asyncio.CancelledError` (reference kills child +
  re-raises), and (b) does not catch `OSError` from `create_subprocess_exec` → an
  out-of-band `OSError` can escape, violating the protocol contract ("only `ProviderError`
  subclasses should escape").

- 🟢 **G1 — no effort plumbing.** Reference maps `effort`→`--effort` for `EFFORT`-capable
  models; agy silently drops `request.effort_level`. Plausibly intentional for Gemini —
  but confirm intent (this is also why `Capability` ended up imported-unused).

- 🟢 **G2 — `time.monotonic` vs reference `time.perf_counter`** for latency. Both fine; noted
  only as a needless divergence.

### Focus 3 — Subprocess security: ✅ GOOD (strongest part of the change)

The security-critical pattern is faithfully ported from the `claude_code_cli` Y2-alpha
MUST-FIX:

- **No shell-injection surface.** `asyncio.create_subprocess_exec(*args)` with a `list` argv
  (no `shell=True`, no string interpolation). `model_id` / `temperature` are discrete argv
  items; prompt text goes over the stdin pipe, never argv.
- **`base_url` fail-closed allowlist** in `__post_init__`: a non-`None` `base_url` not in
  `trusted_base_urls` raises `ConfigError` at construction, before any subprocess. Correct.
- **`_build_child_env()` strips inherited `AGY_BASE_URL`** before optionally injecting the
  allowlisted value → a hostile parent-env value cannot bypass the allowlist. Mirrors the
  `ANTHROPIC_BASE_URL` contract exactly.
- `health_check` runs `agy --version` with the sanitized child env. Consistent.
- stderr transient-marker list is identical to the reference → reasonable classification.

(Caveat outside code scope: that `agy` actually honors `AGY_BASE_URL` is a binary-contract
assumption, not verifiable here. Worth a one-line note in the eventual config example.)

### Focus 4 — Parser robustness: ✅ mostly fail-safe

Content path is genuinely defensive: malformed JSON → `PermanentProviderError`; non-dict
top-level → `PermanentProviderError`; missing `content` → `""`; list-of-blocks handled,
non-str coerced; missing/non-dict `usage` → zeros with `or 0` null-guards; non-str / unknown
`finish_reason` → `"stop"`. Two notes:

- 🟡 **Y3 — tool_call `arguments` shape assumption.** `tc["function"]["arguments"] or {}` is
  handed to `ToolCall.arguments: dict[str, Any]`. OpenAI's actual wire format encodes
  tool-call arguments as a **JSON-encoded string**, not an object — that would raise
  `ValidationError` → `PermanentProviderError`. Low-impact today (tools are rejected upstream,
  so this branch is dead/untested), but it would mis-handle the real shape if ever reached.
- 🟢 **G/E501** at agy_cli_output.py:63 (content-block comprehension) — style only, but
  gate-breaking.

### Focus 5 — Test gap: 🔴 must-fix

- 🔴 **B6 — zero tests.** Parity bar: `claude_code_cli` ships `test_claude_code_cli_provider.py`
  **and** `test_claude_code_output_parser.py`. agy ships neither. A new subprocess provider
  with no tests is a hard must-fix. Required coverage:
  - **provider:** happy path (mocked subprocess); tool-bearing → `ToolsNotSupportedError`;
    timeout → `TransientProviderError` (+ assert child killed); non-zero exit transient vs
    permanent classification; missing binary → `ProviderUnhealthyError`; `health_check`
    true/false; `base_url` not in allowlist → `ConfigError`; `AGY_BASE_URL` env stripping.
  - **parser:** happy path; malformed JSON; non-dict; missing/garbage `usage`; `content` as
    list vs str; unknown `finish_reason`; malformed `tool_call`.
- **Throughline:** a *single* happy-path provider test would have caught B1/B2 on the first
  assertion (the call raises `AttributeError` before returning). The absence of tests is
  precisely why three fatal bugs shipped.

### Focus 6 — Config / docs

- 🟡 **Y4 — `config/llm_providers.yaml.example` not updated.** That file documents each
  provider type under a "Provider types:" header and gives a copy-paste block per provider;
  `agy_cli` is absent → a user cannot discover or configure it (the provider is functional
  only if they already know to write `type: agy_cli`). The `providers/__init__.py` "P1 set"
  docstring *was* updated (good) — the user-facing example was not. Add an `agy_cli` block
  (with the `base_url` / `trusted_base_urls` allowlist note) for parity with the
  `claude_code_cli` entry.
- No ADR / ADR-002 amendment required (additive, non-spine). Correct as-is.

### Nits

- 🟢 **G3** — `ToolsNotSupportedError` message has a stray `" ; "` (space-semicolon): `"…requests
  ; request had …"`.

---

## Must-fix checklist (for the author, before re-review)

1. **B1** `model.default_temperature` → use `request.temperature` only, or add the field /
   drop the `elif` (ModelProfile has no temperature default).
2. **B2** `request.id` → `request.request_id`.
3. **B3** `model_id_used=model.provider_model_id` → `model.id`.
4. **B4** `"\n\n".join(request.system)` → handle `str | None` as a scalar (guard `if request.system`),
   matching the reference. Current code crashes when `system is None` (the default) and
   character-corrupts a non-empty system string.
5. **B5** ruff clean: fix I001 (move `agy_cli` import above `claude_code_cli`), remove unused
   `Capability` import, resolve the `assistant_text` dead variable (see Y1), wrap the two E501
   lines, `asyncio.TimeoutError`→`TimeoutError`.
6. **B6** add provider + parser tests (coverage list above).
7. **Y1** decide multi-turn stdin: currently only system + user messages reach stdin;
   assistant turns are dropped (the `assistant_text` F841 is the fingerprint of this
   half-wired logic). Reference preserves all messages with role labels — match it, or
   document why agy collapses history.
8. **Y2** add kill-on-timeout + `CancelledError` + `OSError`-on-launch handling.
9. **Y3 / Y4 / G1 / G3** as noted (lower priority).

Re-run `ruff check` + `uv run mypy` + `uv run pytest` to green before re-dispatch. B1/B2/B4
each crash the first real invocation, so a happy-path test is the fastest proof of fix.
