---
task_id: P4.2-B5
review: plan-vs-impl
stage: impl
lens: single (R0-A only; requires_cross_family_review=false)
reviewer: senior
verdict: clean
blocking: 0
yellow: 0
green: 3
date: 2026-06-05
---

# P4.2-B5 — Senior plan-vs-impl (impl-stage)

Lens: senior plan-vs-impl only. I check the impl against **my plan**
(`senior-plans/P4.2-B5.md`, B5-1..6) + **ADR-036 (Accepted)**. R0-A runs the
threat-probe in parallel (arch-partner). Verify-cited throughout.

**Verdict: `clean`.** All six atomics delivered, faithful to the plan +
ADR-036, no scope drift, atomic→commit 1:1 (RC-17). The four ratified/absorbed
items (apply_edit Y1 recipe; send_email config-driven HTTP + dual fail-closed;
git_push SSH_AUTH_SOCK named overlay + argv discipline; all-three-via-unchanged-
confirm-path) are all present and asserted. Gates green. Three 🟢 observations
(cosmetic / forward-watch), zero 🟡, zero blocking.

---

## Atomic → commit 1:1 (RC-17) — confirmed

| Atomic | Commit | Files | Drift |
|---|---|---|---|
| B5-1 apply_edit | `f400e5c` | `mutation_tools.py` (new) + `test_mutation_tools.py` | none |
| B5-2 send_email | `ddd2ac3` | `network_tools.py` + `selection.py`(+1) + `email.yaml.example` + tests | none |
| B5-3 git_push | `8ddc52f` | `subprocess_tools.py` + `selection.py`(+1) + tests | none |
| B5-4 wiring | `9ff455b` | `app.py` + `test_e2e.py` | none |
| B5-5 t11/t12 | `5085a51` | `test_constitution.py` | none |
| B5-6 ADR inscription | `6f56a92` | ADR-028 D3 + ADR-030/034/035 cross-refs | none |

Each atomic = exactly one commit, subject names the atomic. No bundling. The two
`selection.py` touches (B5-2 `_NETWORK_TOOL_NAMES`, B5-3 `_SUBPROCESS_TOOL_NAMES`)
were anticipated by the plan (§2 B5-2/B5-3 "Where") and were correctly serialized
(adjacent name-sets, conflict risk) — no merge artifact.

---

## Ratified / absorbed item verification (the dispatch checklist)

### apply_edit — Y1 PINNED write recipe (ADR-036 D3-i; plan B5-1 + t11)
`mutation_tools.py:71-151`. **Faithful to the pinned recipe, all six clauses:**
- Param allowlist `{path, content}` enforced via `_check_disallowed` (`:81`). ✓
- **Bounded content** BEFORE any write (`:90-95`, `MAX_RESULT_BYTES` reused). ✓
- **Check-time containment** via `_check_path` (`:100`) — resolves+`relative_to`,
  rejects traversal/absolute/parent-symlink-escape AND existing escaping
  final-symlink; `apply_edit` *refuses* (raises), read tools only skip. ✓
- **O_NOFOLLOW temp-create + os.replace** (`:108-135`): `mkstemp` in `dest.parent`
  (same-FS), unlink, then `os.open(..., O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o600)`
  — O_NOFOLLOW on the **temp create** (not the dest), O_EXCL rejects pre-existing
  temp; write→fsync→close→`os.replace(temp, dest)` (atomic). ✓
- **Parent-component TOCTOU** inscribed as the named RB-FS residual in the impl
  docstring (`:25-28`). ✓
- **Output TRUSTED** `LocalToolOutput("wrote N bytes to <rel>")`, no `_*_TOOL_NAMES`
  membership (`:147-149`). ✓
- **t11 asserts the chosen strategy** (`test_constitution.py` t11): behavioral
  (traversal refused, existing-escaping-symlink refused + original unmutated,
  oversize refused, mid-write `fsync` failure leaves no partial) + AST guard
  (O_NOFOLLOW referenced on the os.open temp create; **never** a plain
  `open(<dest>, "w")` on the destination). Impl + t11 agree. ✓

### send_email — config-driven HTTP + dual fail-closed (ADR-036 D3-ii; plan B5-2)
`network_tools.py:259-393`. **Faithful:**
- Param allowlist `{to, subject, body}` (`:296`). ✓
- **Config-driven HTTP**: `endpoint`+`api_key_env`+`from_addr`+`allowed_domains`
  from `config/email.yaml` via `_load_email_config` (mirrors `_load_web_search_config`);
  plain `httpx.Client` POST (SSRF N/A — endpoint operator-trusted, not in param
  allowlist). ✓
- **Dual fail-closed**: unconfigured provider → `LocalToolError("not configured…")`
  (`:313-316`); **unconfigured allowlist → fail-closed** (`:319-323`). ✓
- **Domain-allowlist (primary) + optional explicit recipient list** (`:326-345`);
  recipient outside allowlist → `LocalToolError` before send (never sent). Honest
  exfil-by-recipient residual inscribed in `email.yaml.example` + ADR-036 D3-ii. ✓
- **Key-to-provider-header-only**: `Authorization: Bearer {api_key}` only (`:355`);
  never in payload/logs/result; test `test_..._key_in_header_only` asserts. ✓
- **Output untrusted + bounded**: raw send-status, truncated at `MAX_RESULT_BYTES`,
  `send_email ∈ _NETWORK_TOOL_NAMES` (`selection.py:115`) → excerpt-excluded; b46
  drift-sync enforces the pair. ✓

### git_push — SSH_AUTH_SOCK overlay + argv discipline (ADR-036 D3-iii; plan B5-3)
`subprocess_tools.py:227-303`. **Faithful:**
- Param allowlist `{remote, branch}` (`:236`); branch defaults to resolved HEAD
  (`git rev-parse --abbrev-ref HEAD`, scoped_env, no new agent surface). ✓
- **argv-never-shell**: fixed `["git","push",remote,branch]` (`:281`); t9 AST scan
  covers `subprocess_tools.py` free; b55 meta-test re-asserts `_make_git_push` ∈ file. ✓
- **SSH_AUTH_SOCK named overlay (no secret)**: `_GIT_PUSH_ENV_PASSTHROUGH =
  frozenset({"SSH_AUTH_SOCK"})` (`:46`) overlaid via `scoped_env(extra_env=…)`
  (`:296-299`); **no `api_key_env`** → no secret value injected; HOME already in
  `_SAFE_ENV_KEYS`. ✓
- **No --force/--mirror/--delete**: flag-shaped `remote`/`branch` (startswith "-")
  refused (`:255-266`); `_GIT_PUSH_BANNED_FLAGS` defense-in-depth (`:49-51`); t12
  AST+behavioral asserts all five banned flags. ✓
- **Remote-output-untrusted**: raw status via `_dispatch`; `git_push ∈
  _SUBPROCESS_TOOL_NAMES` (`selection.py:102`) → output-untrusted union; b35
  drift-sync enforces. ✓
- 30s timeout in `_SUBPROCESS_TIMEOUTS` (`:40`); rides bounded output + kill-no-orphan. ✓

### Confirm-path actuation + carry-forwards
- **All three actuate via the unchanged ADR-030 confirm path.** `executor.py` diff
  across the slice is **empty** (verified `git diff main...HEAD -- executor.py` = ∅)
  — `_execute_local_call` byte-frozen (4th time). ✓
- **e2e proof**: `test_e2e_apply_edit_confirm_actuates` (`test_e2e.py:321`) drives
  TOOL_CALL_PENDING → approve → TOOL_RESULT "wrote N bytes" + file on disk (proves
  no longer `not_implemented`); `test_e2e_send_email_unconfigured_fail_closed`
  (`:416`) proves absent `email.yaml` → fail-closed, not a crash. ✓
- **Caps in the loop**: `git_push` carries `_is_posture_b_subprocess` (via
  `_SubprocessToolFn`) → subprocess cap; `send_email` carries `_is_network_tool`
  (via `_NetworkToolFn`) → network cap; `apply_edit` is a plain `LocalToolFn` (no
  marker, no cap, like `read_file`). Markers carried correctly; executor unchanged
  applies the caps. ✓
- **No new LLMPurpose**: t3 covers all `tools/`; b55 asserts `mutation_tools.py`
  has no `LLMPurpose`. ✓
- **ADR-028 D3 amendment + cross-refs** (B5-6): status line carries
  `[Amended P4.2-B5 → ADR-036]`; the `:59` no-write note annotated (write IS in the
  set via apply_edit); deferred-tools line strikes apply_edit/send_email/git_push;
  `propose_edit` remains deferred (rev 5, OUT); ADR-030/034/035 each carry the
  cross-ref one-liner. ✓

### Gates
`uv run ruff check src tests` → All checks passed. `uv run mypy --strict src tests`
→ Success, 244 files. `uv run pytest tests/tools/` → all pass (incl. constitution
t1–t12 + b35/b46 drift-sync + b55 free-coverage). ✓

---

## 🟢 Observations (non-blocking; not plan-drift; no architect routing needed)

**🟢-1 — B5-6 commit message overclaims vs the diff (cosmetic; the inscription is
correct).** The `6f56a92` message says it will "remove the 'mutation surface
remains deferred' clause from prior B3/B4 amendment notes," but the diff leaves
those B3/B4 clauses in place. This is the **right** outcome: the ADR-028 status
line is an **append-only amendment log** — each `[Amended P4.2-BN]` entry records
what was true at its own date, and the B5 entry supersedes. Rewriting historical
amendment notes would have been the error. So the inscription is correct; only the
commit message describes an action it (rightly) did not take. No ADR-text fix
needed. Outside my plan's B5-6 acceptance (which only required the B5 annotations
to land — they did).

**🟢-2 — send_email treats <500 HTTP as TOOL_RESULT, only ≥500 as TOOL_FAILED**
(`network_tools.py:379-381`). A provider 4xx (e.g. 401 bad key, 422 bad recipient)
returns the status text as a raw (untrusted, framed, excerpt-excluded) TOOL_RESULT
rather than `LocalToolError`. This is internally consistent with the B3 "tool ran
— here is the status" philosophy (non-zero subprocess exit → TOOL_RESULT) and
leaks no secret (key is header-only; body is the provider's, not our request).
Plan B5-2 acceptance said "provider-error → LocalToolError"; the <500-as-result
split is a defensible narrowing, not a security or containment gap. Flag for the
architect's awareness only.

**🟢-3 — t11 AST guard "Check 2" is permissive** (`test_constitution.py` t11). If
the direct `os.open(..., O_NOFOLLOW)` match misses, the fallback passes when both
`O_NOFOLLOW` and `os.open` appear *anywhere* in the source (not necessarily in the
same call). The current impl satisfies the strict Check 1 path, so the guard binds
today; the looseness only matters if a future refactor separates them. Forward-
watch on the test's strength, not a B5 correctness issue.

---

## Routing

Nothing to route — verdict `clean`, 0 blocking / 0 🟡. The three 🟢 are
awareness-only (cosmetic commit message, a defensible error-class narrowing, a
test-strength forward-watch). Per ADR-008 Amendment 1 (W-005, Route B), state
auto-advances to `awaiting_R0_A` regardless. R0-A (arch-partner, in parallel) is
the single-lens threat-probe; this senior pass found no plan-implied-invariant
drift that R0-A would structurally miss.
