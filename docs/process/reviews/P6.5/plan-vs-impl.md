---
task_id: P6.5
kind: plan-vs-impl
author: senior
surface: product
plan: docs/process/senior-plans/P6.5.md
plan_has_adr: false
reviewed_commit: fb68efc
reviewed_branch: origin/claude/P6.5-impl
requires_cross_family_review: true
verdict: clean
---

# P6.5 — senior plan-vs-impl (git_push remote hardening: transport allowlist + configured-remote restriction)

Reviewed `origin/claude/P6.5-impl @ fb68efc` (single commit, subject `P6.5-G1: git_push remote hardening …`) against `docs/process/senior-plans/P6.5.md`. Read from `main` via `git diff main...origin/claude/P6.5-impl`; did not check out the impl branch. Files changed: exactly the three the plan named — `src/orchestrator/tools/subprocess_tools.py`, `tests/tools/test_subprocess_tools.py`, `docs/decisions/ADR-036-mutation-local-tools.md`. No `.workflow/` change, no stray state-advance commit, no plan-external functional files.

**Verdict: clean.** Both atoms (G1 impl+tests, G1-doc ADR annotation) are faithful to the plan; the two named threat vectors are closed exactly as specified, with the layered defence (configured-name restriction + `GIT_ALLOW_PROTOCOL` transport allowlist) realized on both dispatch paths. Three 🟢 (informational/positive) below; zero 🟡, zero blocking. Gates (ruff/mypy/pytest, t9/t12) are the R0-A/R0-B lens per the dual-lens dispatch — not re-run here.

## Plan-faithfulness — G1 (`subprocess_tools.py`)

| Plan §2 "Where" element | Impl | Faithful |
|---|---|---|
| New constant near `_GIT_PUSH_ENV_PASSTHROUGH` | `_GIT_ALLOW_PROTOCOL = "https:ssh:git:file"` at `:54` | ✓ — matches §5(a) `file`-inclusive choice exactly |
| Configured-remote-name check before the `if posture_resolver is not None:` branch (guards the non-sandbox `_dispatch` RCE path too) | `git remote` list via fixed-argv `run_scoped_command` (`:438-451`), reject if `remote not in configured_remotes` (`:459-463`) — placed before the posture branch at `:470` | ✓ — guards **both** paths; this is the 2a/2b param-level kill |
| `GIT_ALLOW_PROTOCOL` into the push subprocess env | `extra_env["GIT_ALLOW_PROTOCOL"] = _GIT_ALLOW_PROTOCOL` (`:468`) → flows through `_dispatch` + `_sandbox_dispatch` via `scoped_env` overlay | ✓ |
| `GIT_ALLOW_PROTOCOL` on **every** other git invocation in the module | HEAD `rev-parse` (`:407`), new `git remote` list (`:442`), `git remote get-url` in `_resolve_git_remote_host` (`:503`) — all via `scoped_env(extra_env={…})` | ✓ — no git subprocess in the module runs without it |
| `_resolve_git_remote_host` URL-parsing unchanged except env | only the `env=` arg gained the overlay (`:503`); parse branches untouched — now only ever called with a configured name | ✓ |

**Plan-implied invariant — layered defence holds independently.** The configured-remote check kills 2a/2b at the param boundary (inline URLs / `ext::` strings rejected before any push), and `GIT_ALLOW_PROTOCOL` independently kills 2a even for a *configured* remote whose stored URL is `ext::…` (git refuses the transport). Both layers are present and each is exercised by its own test (criteria 1+2). This is exactly the defence-in-depth the plan's §1 2a/2b decomposition required — no drift.

## Plan-faithfulness — acceptance criteria

1. **Input-restriction fail-on-revert (2a+2b via param)** — ✓ `test_git_push_ext_transport_remote_rejected` (`ext::sh -c 'touch …'` → `LocalToolError` match `"not a configured remote"` **and** asserts `not pwned.exists()`) + `test_git_push_inline_url_remote_rejected` (`https://evil/r` → rejected). Both fixtures pre-configure `origin`, so the rejection provably hits the name-check, not "no remotes at all" (plan's explicit requirement).
2. **Transport defense-in-depth (2a independent of name-check)** — ✓ `test_git_push_ext_protocol_blocked_by_allowlist`: configures a real `evil` remote with an `ext::` URL (passes the name-check), asserts `not pwned.exists()`. Runs on the non-sandbox `_dispatch` path (unit `_invoke`, `posture_resolver is None`) — i.e. it proves `GIT_ALLOW_PROTOCOL` blocks `ext::` on exactly the RCE path the plan flagged.
3. **Happy path updated** — ✓ `test_git_push_happy_path_local_remote` now does `git remote add origin <bare>` then `{"remote": "origin", …}` (was inline `remote=str(bare)`, which the restriction now rejects). Faithful to plan criterion 3.
4. **`GIT_ALLOW_PROTOCOL` present in env** — ✓ `test_git_push_allow_protocol_in_env` captures `scoped_env` output and asserts `captured_env["GIT_ALLOW_PROTOCOL"] == _GIT_ALLOW_PROTOCOL`.
5. **Caller-side fixups (promotion-impact)** — ✓ both `test_git_push_ssh_auth_sock_overlaid_when_present` and `_absent_no_key` made `_fake_run` argv-aware: `["git", "remote"]` → `output="origin\n"`, else `"pushed"`. This is precisely the promotion-impact the plan's §5(b) pre-investigation predicted (the new `git remote` list call routes through the same mock). Both fixups present.
6/7. **Constitution + full gate** — argv stays fixed (`["git","push",remote,branch]`, `:466`; `["git","remote"]`, `:439`), no shell, no new `LLMPurpose` → t9/t12/t3 reasoning holds by inspection. Full gate (ruff/mypy/pytest) is the R0-A/R0-B verification surface; not re-run from `main`.

## Plan-faithfulness — G1-doc (ADR-036 annotation)

✓ Line 75 residual bullet annotated `[Annotated P6.5: …]` — reads as **NARROWED, not solved** ("within-config remote still pushable; the P4.3 egress proxy remains the hard boundary"), and names **both** layers (configured-name restriction + `GIT_ALLOW_PROTOCOL` allowlist, `blocks ext::/fd::`). ✓ The optional Reversibility-table row (`:132`) also carries a matching one-line annotation, preserving the existing inline-annotation style. No other ADR text changed; no Decision/Amendment, consistent with `plan_has_adr=false`.

## 🟢 Informational / positive

- **🟢-1 (incidental format churn, defensible).** The diff reflows ~10 sibling call-sites/signatures unrelated to `git_push` (`_check_disallowed`, `_sandbox_dispatch`, `_make_run_tests/_run_lint/_git_blame/_git_log/_git_diff`, several test helpers). These are not net-new churn: `main`'s `subprocess_tools.py` + `test_subprocess_tools.py` currently **fail `ruff format --check`** (the project gate runs `ruff check`, not `ruff format`), so the junior's edit ran `ruff format` on the two files it was already touching, cleaning pre-existing drift. Behavior-preserving; widens the review surface beyond the plan's single-concern framing but does not touch behavior. Not blocking.
- **🟢-2 (fail-closed error handling — aligned with intent).** The `git remote` list call is wrapped `try/except (SubprocessTimeoutError, OSError)` → `configured_remotes = set()`, and a non-zero exit likewise yields `set()`; either way `remote not in set` → `LocalToolError`. The plan didn't specify the error path, but fail-closed (reject on any list failure) is the correct security posture for an irreversible tool. Noted as an intent-aligned realization choice, not a drift.
- **🟢-3 (defense-in-depth assertion slightly looser than plan note).** Criterion 2's test asserts `"exit_code=" in result.content` rather than the plan's "non-zero-exit". The load-bearing security assertion (`not pwned.exists()`) is present and exact; the exit-code looseness is immaterial. No action needed.

## State

Per ADR-008 Amendment 1 (W-005, Route B): state auto-advances `awaiting_senior_plan_vs_impl → awaiting_R0_A` on this verdict (no short-circuit to `awaiting_architect_decision`). `requires_cross_family_review: true` → full impl-stage dual-lens (R0-A + R0-B), subprocess-injection threat-probe lens. No architect decision is open: the one surfaced realization sub-choice (`file` in the transport allowlist, plan §5(a)) was already in the plan the architect dispatched to junior; impl used `https:ssh:git:file` as specified.
