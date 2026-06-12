---
task: agy-cli-provider
reviewer: senior
lens: design + completeness (senior perspective)
reviewed_branch: origin/claude/agy-cli-provider
reviewed_commit: 626c6a2
base: origin/main
verdict: blocking
summary: >
  Registration is structurally complete (enum + registry map + package
  __init__), but the provider does not type-check or run: three hard
  defects (wrong LLMRequest field, wrong model_id_used field+type,
  wrong LLMRequest.system shape) plus an unused import that fails ruff.
  Zero tests, no config example entry, and no ADR/design note for a
  *product*-surface provider. Cannot merge as-is.
---

# Senior review — agy (Antigravity) CLI provider

External, brief-bypassing direct write. 5 files / +291 LoC.
Reviewed by `git diff origin/main...origin/claude/agy-cli-provider`
(stayed on `main`, no checkout). Reference baseline:
`claude_code_cli` provider (`ADR-003`, two test files).

Surface is **product** (`src/orchestrator/llm/…`), so the normal
product-correctness bar applies — this is not dev-harness scope.

---

## Verdict: BLOCKING

Four defects below are individually merge-blocking; B1–B3 mean the
provider crashes or mis-records on its first real call, B4 fails the
ruff gate. Tests would have caught B1–B3 — their absence (item C1) is
how broken code reached review.

---

## A. Blocking correctness defects

### B1 — `request.id` does not exist → AttributeError on every call
`providers/agy_cli.py` (the `parse_agy_cli_output(...)` call,
`request_id=request.id`).

`LLMRequest` exposes **`request_id`**, not `id`
(`types.py:175`; model is `frozen=True, extra="forbid"`). `request.id`
raises `AttributeError` at runtime and is a mypy error. The reference
provider correctly uses `request.request_id`
(`claude_code_cli.py:272`).

**Fix:** `request_id=request.request_id`.

### B2 — `model_id_used=model.provider_model_id` — wrong field and wrong type
`providers/agy_cli.py` (call into the parser).

The Protocol mandates `model_id_used` be populated from **`model.id`**
(`protocol.py:92`, "`model_id_used` from `model.id`"); the reference
passes `model_id_used=model.id` (`claude_code_cli.py:274`). agy passes
`model.provider_model_id`, which is:
- **semantically wrong** — the audit log
  (`LLMResponse.model_id_used`) must record the canonical model id, not
  the provider-wire model string. `model_id_requested` vs `model_id_used`
  is the fallback-audit contract (`types.py:220–238`); recording the
  wire string breaks it.
- **a type error** — `provider_model_id` is a plain `str`
  (`types.py:279`) but `parse_agy_cli_output(model_id_used: ModelId, …)`
  (parser sig) and `LLMResponse.model_id_used: ModelId` are the
  `ModelId` NewType. mypy rejects str→ModelId.

**Fix:** `model_id_used=model.id`.

### B3 — `request.system` treated as a list; it is `str | None`
`providers/agy_cli.py`:
`system_text = "\n\n".join(request.system)`.

`LLMRequest.system` is **`str | None`** (`types.py`, `system: str | None
= None`). Consequences:
- `system is None` (the default) → `TypeError: can only join an
  iterable` — i.e. **every request without a system prompt crashes**.
- `system` a real string → `"\n\n".join("abc")` splices *characters*
  (`"a\n\nb\n\nc"`), silently corrupting the prompt.

The reference guards correctly and treats it as a scalar string:
`if request.system: prompt_parts.append(f"[System]\n{request.system}")`
(`claude_code_cli.py:217–218`).

**Fix:** `system_text = request.system or ""` (then keep the existing
`if system_text:` guard).

### B4 — unused `Capability` import → ruff F401 (gate fails)
`providers/agy_cli.py` imports `Capability` (in the `types` import
block) but never references it — agy does no effort mapping, so unlike
the reference (`claude_code_cli.py:213`, `Capability.EFFORT`) there is
no use. ruff F401 fails the lint gate.

**Fix:** drop `Capability` from the import.

---

## B. Completeness gaps (vs `claude_code_cli`)

### C1 — Zero tests (reference has two: provider + parser)
No `tests/llm/test_agy_cli_provider.py`, no
`tests/llm/test_agy_cli_output_parser.py`; `grep -rn agy tests/` →
nothing. The reference ships `test_claude_code_cli_provider.py` +
`test_claude_code_output_parser.py`. A single unit test would have
caught B1–B3. **Required scope to match the standard:**
- **Parser** (`test_agy_cli_output_parser.py`): valid envelope →
  `LLMResponse` (content str + content-block-list flattening, usage
  mapping, each `_STOP_REASON_MAP` branch + unknown→`stop`);
  non-JSON → `PermanentProviderError`; non-object JSON →
  `PermanentProviderError`; malformed `tool_calls` →
  `PermanentProviderError`.
- **Provider** (`test_agy_cli_provider.py`): `call()` flattens
  stdin + builds argv (incl. `--temperature` from request vs
  model default); `request.tools` → `ToolsNotSupportedError`; missing
  binary → `ProviderUnhealthyError`; timeout → `TransientProviderError`;
  non-zero exit with/without a transient stderr marker →
  `Transient`/`PermanentProviderError`; `health_check()` true/false
  paths; `__post_init__` base_url allowlist (ConfigError) +
  `_build_child_env` strips `AGY_BASE_URL`.

### C2 — Config example not updated
`config/llm_providers.yaml.example` has a `claude_code_cli` block
(`type:` + `cli_path:` + base_url/trusted_base_urls comments) and the
header provider-list comment. No `agy_cli` entry was added. Operators
have no registered example for the new provider. **Add** an `agy_cli`
block mirroring the `claude_code_cli` one (cli_path `agy`, the
`AGY_BASE_URL`/trusted_base_urls comment pair) **and** the header
comment line.

### C3 — No ADR / design note for a product-surface provider
`claude_code_cli`'s structural `can_use_orchestrator_tools() → False`
is justified by a dedicated **ADR-003**, and the method carries a
"see ADR-003 … do not override" comment. agy returns `False` with no
comment and no ADR. The `ProviderType` docstring still reads
"See ADR-002 for the P1 set" — agy is a *new, post-P1* provider type
extending that contract. See item D below for the routing decision.

### C4 — Minor: bootstrap error string not generalized
`bootstrap.py:159` names the `claude_code_cli` provider entry in an
error message. Not agy-specific and not blocking, but the
CLI-provider-family hint now omits agy. Flag for whoever owns the
follow-up; do not bundle into the fix commit.

---

## C. Design / abstraction observations (non-blocking)

- **Alignment is mostly good.** The dataclass shape, `__post_init__`
  base_url allowlist, `_build_child_env` env-stripping, the
  `_TRANSIENT_STDERR_MARKERS` set, and the `ProviderUnhealthy /
  Transient / Permanent` categorization mirror the reference faithfully.
  No abstraction-external coupling or scope expansion was introduced
  (router stays Protocol-structural; no new `LLMPurpose`; registration
  is the canonical enum + `PROVIDER_TYPE_REGISTRY` + package `__init__`
  — all three present and consistent).
- **Subprocess lifecycle is weaker than the reference (robustness, not
  correctness).** agy catches only `asyncio.TimeoutError` /
  `FileNotFoundError`; the reference also (a) catches
  `asyncio.CancelledError` and **kills + reaps** the child
  (`proc.kill(); await proc.wait()`) on both timeout and cancellation,
  and (b) maps `OSError` at spawn to `ProviderUnhealthyError`. As
  written, an agy timeout/cancellation **leaks the subprocess** (no
  kill). Recommend porting the reference's timeout/cancel cleanup block.
- **Dead tool-parsing branch.** The parser builds `ToolCall`s from
  `tool_calls`, but the provider hard-rejects `request.tools`
  (`ToolsNotSupportedError`) and advertises
  `can_use_orchestrator_tools() → False`, so this path is unreachable
  in normal operation. It also assumes OpenAI-shaped
  `function.arguments` as a **dict**, whereas OpenAI emits a JSON
  *string* (would `ValidationError`→`PermanentProviderError`). Either
  delete the branch (consistent with the no-tools stance) or make it
  correct + tested — but don't ship speculative, untested,
  inconsistent code.
- Cosmetic: `time.monotonic()` vs the reference's `time.perf_counter()`
  for latency — both fine, no action needed.

---

## D. Process: needs an architect routing decision

This bypassed brief→plan and touches a **product** surface. Two
process questions are the architect's to route (not senior's to
decide):

1. **ADR for the new provider type.** Does registering `agy_cli`
   warrant a light **ADR-002 amendment** (it extends ADR-002's
   enumerated provider set), or a dedicated mini-ADR à la ADR-003
   (to inscribe the structural `can_use_orchestrator_tools() → False`
   stance and the Gemini-CLI assumptions: `--json` envelope shape,
   `--model`/`--temperature` flags, `AGY_BASE_URL` env)? My read: a
   short ADR-002 amendment registering the type **plus** a one-paragraph
   note on the no-tools rationale is the minimum to match how
   claude_code_cli is documented. **Architect call.**
2. **Path back into the workflow.** Because B1–B3 require code changes
   and C1 requires a real test suite, my recommendation is to route the
   fix + tests through a **junior impl cycle** (this is not an
   additive, review-and-merge-direct change), rather than amending the
   external commit in place.

---

## Required-before-merge checklist

- [ ] B1 `request.request_id`
- [ ] B2 `model_id_used=model.id`
- [ ] B3 `request.system or ""`
- [ ] B4 drop unused `Capability` import
- [ ] C1 parser + provider test files (scope above)
- [ ] C2 `agy_cli` block in `llm_providers.yaml.example` + header line
- [ ] C3/D ADR-002 amendment or mini-ADR — **architect routes first**
- [ ] gates green: ruff + mypy (strict) + pytest

Recommend porting the reference's timeout/cancel subprocess-cleanup
(C-section) in the same cycle; C4 bootstrap string and the dead
tool-parse branch are dispositioned by the architect.
