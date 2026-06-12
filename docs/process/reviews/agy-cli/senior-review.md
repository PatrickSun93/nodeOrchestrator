---
task: agy-cli-provider
reviewer: senior
lens: design + completeness (senior perspective)
reviewed_branch: origin/claude/agy-cli-provider
reviewed_commit: 4628781
base: 626c6a2 (original external commit)
round: 2 (re-review; supersedes round-1 blocking)
verdict: clean
summary: >
  All four round-1 blocking defects are fixed and proven by the new
  tests (B1 request_id, B2 model_id_used=model.id, B3 system str|None,
  B4 Capability import). Provider + parser test suites are present,
  comprehensive, and directly assert the fixed behaviors. Config example
  block + header line + the TestExampleConfigs count caller-update are in;
  ADR-002 carries an "Implemented" amendment note registering the type.
  Design aligns with the claude_code_cli reference and actually improves
  on it (subprocess kill/reap + OSError mapping ported; a latent 5th
  defect — a reference to the nonexistent model.default_temperature —
  removed). No scope expansion: no new LLMPurpose, router untouched,
  only the expected file set. Cleared to merge.
---

# Senior re-review — agy (Antigravity) CLI provider (round 2)

Re-review of `origin/claude/agy-cli-provider @ 4628781` after the junior
absorbed round-1 senior + R0-A blocking feedback. Read via
`git diff 626c6a2..origin/claude/agy-cli-provider` — stayed on `main`,
no checkout. Round-1 verdict was **blocking** (4 defects + zero tests +
no example + no ADR note); this file supersedes it.

Surface is **product** (`src/orchestrator/llm/…`); the full
product-correctness bar applies.

---

## Verdict: CLEAN

Every round-1 required-before-merge item is satisfied. Verified by
static reading of the diff + tests + source against the reference
provider; gate execution is out of this role's scope.

---

## A. Round-1 blocking defects — all fixed

### B1 — `request.id` → `request.request_id` ✅
`providers/agy_cli.py:185` now passes `request_id=request.request_id`
(matches `LLMRequest` field, `types.py:175`). The happy-path tests
(e.g. `test_basic_call_invokes_cli`) would raise `AttributeError` if
this regressed.

### B2 — `model_id_used=model.provider_model_id` → `model.id` ✅
`providers/agy_cli.py:187` now passes `model_id_used=model.id`,
satisfying the Protocol contract (`protocol.py:92`) and the `ModelId`
type. **Directly asserted**: `test_model_id_used_is_model_id` checks
`resp.model_id_used == ModelId("agy_gemini_flash")` (the canonical id),
not the wire string `gemini-2.0-flash`. The fallback-audit contract
(`model_id_requested` vs `model_id_used`) is now honoured.

### B3 — `"\n\n".join(request.system)` → `request.system or ""` ✅
`providers/agy_cli.py:127` treats `system` as the scalar `str | None`
it is, mirroring the reference. **Two regression tests pin both
failure modes I called out**: `test_system_none_handled` (the default
`None` no longer crashes; no `[System]` block emitted) and
`test_system_str_sent_as_block` (a real string is sent whole, with an
explicit assert that it is *not* character-split).

### B4 — unused `Capability` import dropped ✅
The `Capability` symbol is removed from the `types` import block; agy
does no effort mapping, so there is no use. ruff F401 trigger gone.

---

## B. Completeness gaps — all closed

### C1 — Tests ✅ (was: zero)
Both files now ship and are genuinely effective, not box-ticking:

- **`test_agy_cli_provider.py`** (8 classes): tools-rejection;
  happy-path argv/stdin construction; temperature from-request /
  absent-when-unset; the two B3 system cases; multi-role stdin
  flattening; the B2 `model_id_used` assertion; full error
  classification (FileNotFound + OSError → `Unhealthy`, rate-limit/503
  stderr → `Transient`, plain non-zero → `Permanent`, timeout →
  `Transient`); **subprocess kill on timeout**, **kill-failure does
  not mask the timeout**, **cancellation kills child and re-raises
  `CancelledError`**; health-check true/false/timeout; base_url
  allowlist (accept / reject / empty-allowlist / none); and
  `_build_child_env` AGY_BASE_URL stripping incl. the end-to-end
  `call()`-passes-stripped-env assertion.
- **`test_agy_cli_output_parser.py`**: str + content-block-list
  flattening, non-text-block skipping, non-str coercion, missing
  content/usage defaults, every `_STOP_REASON_MAP` branch +
  unknown/empty → `stop`, non-str finish_reason; and the three
  `PermanentProviderError` paths (non-JSON, non-object JSON, malformed
  tool_call). Asserted `match=` strings line up with the parser source
  (`agy_cli_output.py:54/57/86`).

A single one of these would have caught B1–B3 — the round-1 root cause
(broken code reaching review with no test) is closed.

### C2 — Config example ✅
`config/llm_providers.yaml.example` gains the `google_via_agy` block
(`type: agy_cli`, `cli_path: agy`, `timeout_s`, the
`base_url`/`trusted_base_urls` fail-closed comment pair) plus the
header provider-list comment line — mirroring the `claude_code_cli`
entry. **Promotion-impact caller-update honoured**: the globbed
`TestExampleConfigs.test_load_example_providers` count was bumped 5→6
with the comment updated — exactly the kind of caller-side update that
otherwise resurfaces as a Y finding (pre-investigation rule (b)).

### C3 / D — ADR note ✅
ADR-002 carries a dated `2026-06-11 (agy-cli-provider) — Implemented`
amendment: registers `ProviderType.AGY_CLI` under the same
"new type = new module + `PROVIDER_TYPE_REGISTRY` entry" contract, and
inscribes the structural stance (`can_use_orchestrator_tools() → False`,
`call()` rejects tools, no new `LLMPurpose`, spine/routing unchanged).
The method now also carries the "structural property … do not override"
comment the reference has. This matches the minimum I recommended
(ADR-002 amendment + no-tools rationale note); architect's routing call
on amendment-vs-mini-ADR was satisfied by the amendment form.

---

## C. Design / abstraction — aligned, and improved

- **Reference alignment holds.** Dataclass shape, `__post_init__`
  base_url allowlist, `_build_child_env` stripping, transient-stderr
  marker set, and the Unhealthy/Transient/Permanent categorization all
  mirror `claude_code_cli` faithfully. Registration is the canonical
  trio (enum `AGY_CLI`, `PROVIDER_TYPE_REGISTRY` map, package import) —
  all present and consistent.
- **My round-1 non-blocking robustness observation was absorbed.** The
  subprocess lifecycle now kills + reaps the child on both timeout and
  cancellation, re-raises `CancelledError`, and maps spawn-time
  `OSError` → `ProviderUnhealthyError`. The leak I flagged is gone, and
  it is tested.
- **A latent 5th defect was removed.** The original `elif
  model.default_temperature is not None` referenced an attribute that
  does not exist on `ModelProfile` (`grep default_temperature src/` →
  nothing) — it would have been an `AttributeError` / mypy error on the
  no-request-temperature path. The junior dropped the branch; the
  reference provider sets no temperature flag at all, so this is the
  correct resolution. `request.temperature` (the kept path) is valid
  (`types.py:371`).
- **Dead tool-parse branch** (parser builds `ToolCall`s though the
  provider hard-rejects tools): retained but now tested with the
  dict-shaped `arguments` it assumes. This was architect-dispositioned
  in round 1 ("delete or make correct + tested"); the junior took the
  latter option. Unreachable in normal operation, non-blocking. If a
  future cycle ever enables tools here, the OpenAI JSON-*string*
  `arguments` shape will need handling — noted, not in scope now.

## D. Scope / no-expansion check ✅
Diff is the expected 8 files only: provider, parser, config_loader
(alphabetical import reorder), example config, ADR note, two new test
files, and the one example-count caller-update. No `.workflow/` churn,
no new `LLMPurpose`, router/spine untouched, no abstraction-external
coupling. No out-of-plan expansion.

---

## Required-before-merge checklist (round 1) — all met

- [x] B1 `request.request_id`
- [x] B2 `model_id_used=model.id` (+ asserted)
- [x] B3 `request.system or ""` (+ both cases asserted)
- [x] B4 drop unused `Capability` import
- [x] C1 parser + provider test suites (effective, behavior-asserting)
- [x] C2 `agy_cli` example block + header line + TestExampleConfigs caller-update
- [x] C3/D ADR-002 amendment note registering the type + no-tools rationale
- [x] subprocess timeout/cancel cleanup ported (round-1 C-section rec)

Cleared to merge. Recommend gates (ruff + mypy --strict + pytest) run
once more in CI/junior environment before the merge button, per
standard practice — the static read shows nothing that should fail them.
