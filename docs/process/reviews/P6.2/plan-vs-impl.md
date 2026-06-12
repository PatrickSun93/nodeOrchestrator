---
task_id: P6.2
round: plan-vs-impl
reviewer: senior
verdict: needs_architect          # Y1: ruff-format gate leg fails on the C1 test file (plan §4 "full gate green" not met) — trivial/mechanical, C1+D1 logic faithful & fail-on-revert-verified
findings_count:
  blocking: 0
  yellow: 1
  green: 2
reviewed_commit: 5838ce3
reviewed_branch: origin/claude/P6.2-impl
plan: docs/process/senior-plans/P6.2.md
surface: product
lens: plan-vs-deliverable faithfulness (senior's non-overlapping audit surface)
---

# P6.2 — senior plan-vs-impl review

## Lens + scope

This is the **senior plan-vs-impl** lens: does the impl faithfully realize *the plan
I wrote* (`docs/process/senior-plans/P6.2.md`) — every acceptance criterion met, every
out-of-scope boundary respected, no plan-implied invariant silently drifted, no
plan-外 expansion. It is **non-overlapping** with the external reviewers' deliverable-vs-spec
lens. I formed this assessment independently before reading any other review artifact;
I did **not** incorporate R0-B's findings (its lens is runtime-integration + failure-mode,
a different surface — see §Ordering note).

Reviewed: `origin/claude/P6.2-impl @ 5838ce3`, two atomic commits
(`bf7c9c9` C1, `5838ce3` D1) against `origin/main`. Diff touches **exactly** the six
files the plan named (`openai_compatible.py`, `router.py`, `llm_adapter.py`, `ADR-002`,
`tests/llm/test_openai_compatible_provider.py`, new `tests/api/test_llm_adapter.py`) —
**zero plan-外 expansion**, no stray `.workflow/` self-advance commit on the impl branch.

**Gate** (fresh `--all-extras` worktree on 5838ce3): `ruff check` clean, `mypy`
`Success: no issues found in 310 source files`, full `pytest exit=0` (zero failures).
**But `ruff format --check` FAILS** on `tests/llm/test_openai_compatible_provider.py`
(verified with the repo's `line-length=100` config) — see **Y1**. The plan's §4 forcing
function requires the *full* gate green (`docs/contributing.md:195`: ruff includes
**format**), so the slice does **not** currently pass its own forcing function. C1+D1
logic is faithful and fail-on-revert-verified (below); the miss is purely the format leg.

---

## C1 — empty/blank tool_call arguments → `{}` (`bf7c9c9`)

| Plan AC | Impl | Verdict |
|---|---|---|
| **1.** `strip()`-guard; `""` / `"   "` → `{}` | `openai_compatible.py:274-279` — `if isinstance(args_raw, str): arguments = json.loads(args_raw) if args_raw.strip() else {}` else `args_raw or {}` | ✅ faithful |
| **2.** malformed `"{bad"` still `PermanentProviderError` | `except (KeyError, json.JSONDecodeError, ValidationError)` at `:287` **untouched**; `json.loads("{bad")` still raises | ✅ |
| **3.** **missing** `arguments` key still Permanent (do **not** widen) | `args_raw = tc["function"]["arguments"]` access untouched → `KeyError` → caught at `:287` → Permanent; `None`/absent → `args_raw or {}` is the **pre-existing** falsy branch, not widened | ✅ scope boundary respected |
| **4.** fail-on-revert test (`""`, `"   "`, `"{bad"`) | `TestToolCallArgumentsNormalization` — three cases present | ✅ |

**Fail-on-revert independently exercised**: reverting the guard to the single-line pre-fix
form makes `test_empty_string_arguments_normalizes_to_empty_dict` and
`test_blank_string_arguments_normalizes_to_empty_dict` **fail** (`json.loads("")` →
`PermanentProviderError: malformed tool_call`). Genuine revert-coupling confirmed.

**Out-of-scope honored**: no change to `types.py` / `ToolCall`, the `:285` except clause,
or the `.call()` HTTP path. Architect-ratified **C-lean** (`None ≠ empty-string`) preserved
exactly.

---

## D1 — call-time transient fallback (`5838ce3`)

Mechanism is **D-mech-A** as the plan settled (§5): router exposes the ordered viable
list; adapter iterates. Faithful on every point.

| Plan AC | Impl | Verdict |
|---|---|---|
| **1.** router stays pure (zero `.call()`, health_check only) | `select_viable_routes` (`router.py:290-438`) makes **no** `provider.call()` — only `health_check()`; `.call()` loop lives in the **adapter** | ✅ `router.py:15` invariant held; constitution tests pass |
| **2.** `select_model_and_provider` observable contract preserved exactly | **byte-unchanged** (zero diff). Junior chose the standalone-duplication factoring (plan-sanctioned: "either factoring is acceptable") rather than delegate. Strongest possible preservation — its ~30 `test_router.py` callers + constitution refs untouched | ✅ |
| **3.** adapter loop: transient→next, permanent→propagate, success→return, `model_id_requested=route.model_id_requested` | `llm_adapter.py:85-104` — `for route in routes:` `return await route.provider.call(...)` then `except TransientProviderError: <append trace, continue>`; only Transient caught (Permanent propagates) | ✅ |
| **4.** all-transient → `NoSuitableModelError` + per-route trace `{model_id, provider_id, accepted: False, reason: "call-time transient: …"}` (ratified option **(b)**) | `llm_adapter.py:105-108` raises `NoSuitableModelError(decision_trace=call_trace)`; each entry `dataclasses.asdict(RouteCandidate(...reason=f"call-time transient: {exc}"))` | ✅ shape mirrors `RouteCandidate.asdict` |
| **5.** audit invariant `requested(head) != used(fallback)` | by construction — every `RouteResult.model_id_requested = agent_config.default_model` (chain head); test asserts `model_id_requested == PRIMARY_ID`, `model_id_used == FALLBACK_ID`, `!=` | ✅ |
| **6.** fail-on-revert test in `tests/api/test_llm_adapter.py`; provider double via local fake (no provider-error in prod code) | three sub-cases present (`test_transient_primary_falls_to_fallback`, `test_permanent_primary_propagates_no_fallback`, `test_all_transient_raises_no_suitable_model_error`); double is local `_ErrorOnCallProvider` — **no** error-injection added to production providers | ✅ |
| **7.** ADR-002 D4 "Implemented" note, dated, same weight as agy-cli note; `plan_has_adr=false`, no Accept gate | `ADR-002.md:207-215` — `### 2026-06-12 (P6.2 / D1) — Implemented (call-time transient fallback)`; records (i) call-time half implemented via D-mech-A + (ii) safe-because side-effect-free content-gen (no double-actuation, ADR-003) | ✅ matches agy-cli precedent style/weight |

**`select_viable_routes` faithfulness check** (the load-bearing new code): its per-candidate
filter block (registry → capability → tools → health_check → accept) is **line-for-line
identical** to `select_model_and_provider` (`router.py:210-282`), differing only in that it
appends each pass to `viable` and continues instead of returning the first. The **first**
element of its return therefore carries the byte-identical `decision_trace` that
`select_model_and_provider` would return — the contract-preservation argument (plan §5 /
AC D1.2) holds by structural identity, and is additionally proven by `select_model_and_provider`
being literally untouched.

**Fail-on-revert independently exercised**: reverting the adapter loop to a single
`routes[0].provider.call(...)` makes `test_transient_primary_falls_to_fallback` **fail**
(primary's transient propagates instead of the fallback answering) and
`test_all_transient_raises_no_suitable_model_error` **fail** (single call re-raises
`TransientProviderError` instead of `NoSuitableModelError`). `test_permanent_*` still passes
under revert — correct, Permanent propagates in both forms. Genuine revert-coupling.

**Forcing functions honored**: no new `LLMPurpose` (diff on `purposes.py` is empty —
verified); constitution suite (`tests/{llm,mcp,plugins,tools}/test_constitution.py`),
`test_router.py`, and `test_e2e_fallback.py` (the health_check half) all pass unchanged.

**Out-of-scope honored**: no same-provider retry/backoff; no `.call()` loop inside the
router (D-mech-B/C rejected); no change to the 429/5xx/timeout → `TransientProviderError`
mapping; no enrichment of the router's pre-call trace beyond the exhaustion raise.

---

## Findings

One 🟡 (gate-green forcing-function miss), no blocking. Plus two 🟢 informational.

- **🟡-Y1 (plan §4 "full gate green" not met — `ruff format`).** `ruff format --check`
  reformats `tests/llm/test_openai_compatible_provider.py`: the three new
  `_make_provider(lambda r: httpx.Response(200, json=_tool_call_response(...)))` lines in
  `TestToolCallArgumentsNormalization` are wrapped across three lines but fit on one at the
  repo's `line-length=100`, so `ruff format` collapses them. I confirmed this with the repo's
  ruff config (not default-88). The junior evidently ran `ruff check` (passes) but not
  `ruff format` before commit. The plan's §4 forcing function — "Full gate green: ruff +
  mypy + pytest" — and `docs/contributing.md:195` ("`ruff check` **and `ruff format`** must
  pass") make this a genuine gate-green miss → **`needs_architect`**. **Trivial / mechanical,
  zero logic or coverage impact**; remediation is `ruff format` + recommit on the impl branch.
  (This is the same defect R0-A independently flagged as its Y1; I verified it under my own
  plan §4 forcing-function lens.)

Two 🟢 informational notes (both **plan-sanctioned**, surfaced for visibility only —
neither is a drift against the plan):

- **🟢-1 (DRY / latent-divergence).** `select_viable_routes` **duplicates** ~50 lines of
  the per-candidate filter block from `select_model_and_provider` rather than the two
  sharing a private helper. The plan **explicitly authorized** this ("Junior may factor …
  *or* … delegate … Either factoring is acceptable; the constraint is the unchanged
  observable contract, not the internal shape") — so this is **within scope, not a
  finding against the impl**. The only latent cost: a future change to the candidate-filter
  logic must be mirrored in both functions or they silently diverge. Worth a sentence in
  the meta/retro as a future-refactor candidate; **does not gate this slice**.
- **🟢-2 (informational).** With the adapter switched to `select_viable_routes`,
  `select_model_and_provider` now has **no `src/` caller** — it remains as the single-route
  public contract exercised by its ~30 `test_router.py` callers + constitution refs. This is
  the plan's deliberate contract-preservation choice (plan §5 back-compat constraint), **not**
  dead code. Noted only so a future reader doesn't mistake it for unused.

---

## Verdict: `needs_architect`

**C1 + D1 logic is faithful to the plan** — every acceptance criterion met, every
out-of-scope boundary respected, both fail-on-revert tests genuinely revert-coupled (I
re-ran the reverts myself), no plan-外 expansion, no plan-implied logic drift. `ruff check`
+ `mypy` + `pytest` all green. The **only** gap is **Y1**: `ruff format` was not run, so the
slice fails the plan's own §4 "full gate green" forcing function on the format leg
(one C1 test file, mechanical). That single miss is what moves this off `clean` →
`needs_architect`. Trivial to remediate (`ruff format` + recommit). The two 🟢 notes are
plan-sanctioned and informational.

> **Verdict correction note (RC-10).** This file was first committed (`90e9a12`) as
> `verdict: clean` — at that point I had run only `ruff check`, not `ruff format`, and so
> over-claimed "full gate green." On verifying the format leg I found Y1 and corrected the
> verdict to `needs_architect`. The logic-faithfulness conclusion is unchanged; only the
> gate-green claim and verdict are corrected. Flagging the over-claim transparently rather
> than silently editing.

### Ordering / concurrency note (surfaced)

Three review artifacts now sit on local `main` against the same `5838ce3`, committed
near-simultaneously by independent sessions, with `origin/main` still at `2029d4d`
(**none pushed**):

- `2029d4d` — **R0-B** (cross-family, runtime-integration lens): `needs_architect`, 3🟡
- `90e9a12` — **this plan-vs-impl** (senior, plan-faithfulness lens): `needs_architect`, 1🟡 (Y1)
- `275aea2` — **R0-A** (architect-partner, deliverable-vs-spec lens): `needs_architect`, Y1 + O1

The post-commit hook has auto-advanced state to **`awaiting_architect_decision`** (all three
verdicts non-clean). I preserved cross-lens independence by **not** absorbing R0-A/R0-B
findings into this review (I confirmed Y1 under my own §4 forcing-function lens, not by
copying theirs). **I am not pushing**: the push would carry the concurrent R0-A commit
(not mine), and routing the three `needs_architect` sets is the architect's call now that
state is `awaiting_architect_decision`. Surfacing to the architect for the routing pass.
