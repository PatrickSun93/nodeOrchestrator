---
task_id: P6.9
kind: R0-A
stage: impl
surface: product
reviewer: architect-partner
verdict: clean
cycle: 1
reviewed_branch: origin/claude/P6.9-impl
reviewed_sha: 78d00fe74dc1fb114d524ec36296615c2672aa59
atoms: [P6.9-110 (git_push glob-refspec reject), P6.9-109 (apply_edit .git/-deny + ADR-036 D3-i amendment + t11)]
adrs_in_play: [ADR-036 D3-i (apply_edit containment — amended in place), ADR-036 D3-iii (git_push input-validation — annotated)]
spine_frozen: true          # zero diff to _execute_local_call / autonomy gate / confirm-then-execute; no new LLMPurpose
new_adr: false              # ADR-036 amended in place (D3-i bullet + residuals row), no new ADR
gates: { ruff: pass, ruff_format: pass (313 files), mypy: pass (310 files), pytest_full: pass (rc=0) }
fail_on_revert: { p6_9_110: verified, p6_9_109: verified (t11 fails on revert) }
based_on: docs/process/architect-briefs/P6.9.md (Ratification 2026-06-15), docs/process/senior-plans/P6.9.md
requires_cross_family_review: true   # R0-B runs in parallel; this verdict feeds the architect's synthesis
---

# P6.9 — R0-A (impl stage): two git_push / apply_edit security follow-ons

**Verdict: `clean`.** Both atoms implement the architect-ratified direction exactly, the spine is byte-frozen, no new ADR / no new `LLMPurpose`, independent gates are green, and fail-on-revert is verified for **both** atoms (including the dispatch-pinned "revert `.git/`-deny ⇒ t11 FAIL"). No Y findings, no blocking findings. Two non-blocking 🟢 polish notes in §5 — neither needs routing.

## 1. Scope & method

- Reviewed `origin/claude/P6.9-impl` @ `78d00fe` **without checkout** — `git diff origin/main...origin/claude/P6.9-impl` + `git show <sha>:<path>` reads. Shared worktree stayed on `main`.
- Gates run **independently** in an isolated detached worktree (`/mnt/d/devitems/p69-gate-wt` @ 78d00fe) after `uv sync --all-extras` (per the isolated-gate-run-extras discipline — fastapi/mcp present, no false import errors).
- Diff surface: 6 files, +182/−5 — `mutation_tools.py` (+11), `subprocess_tools.py` (+10/−1), `ADR-036` (2 single-line annotations), `test_constitution.py` (t11/t12 +56), `test_mutation_tools.py` (+44), `test_subprocess_tools.py` (+62/−2). Exactly the plan's file set; no scope spill.
- Commits = two atoms, one each, named per plan §3 (RC-17 atomic discipline):
  - `b1d78d4 P6.9-110: git_push reject glob (*) refspec + accurate guard message (ADR-036 D3-iii)`
  - `78d00fe P6.9-109: apply_edit deny .git/ writes + ADR-036 D3-i carve-out + t11 (#109 config-poisoning)`
  - No stray `.workflow/` state-advance commit on the impl branch (diff stat carries no `.workflow/` file).

## 2. Per-atom verification (against the dispatch checklist + brief/plan acceptance)

### P6.9-110 — git_push glob-refspec reject + message reword (`subprocess_tools.py:440-445`)

The `*` guard is placed after the `:`/`+`-prefix check and before banned-flags / configured-remote resolution — rejected early, before any argv build or subprocess.

| Dispatch / acceptance item | Evidence | ✓ |
|---|---|---|
| `branch` containing `*` glob → `LocalToolError` | `if "*" in branch:` — `*` anywhere (no git refspec glob uses anything but `*`; git branch names cannot contain `*`, so no false-positive on legit names) | ✓ |
| `refs/heads/*:refs/heads/*` rejected | covered by `"*" in branch`; behavioral test `test_git_push_glob_refspec_rejected` + t12 | ✓ |
| plain name (`main`) + simple `src:dst` (`main:other`) still accepted | neither starts `:`/`+` nor contains `*`; `test_git_push_simple_src_dst_not_over_blocked` sets up a real bare remote and asserts the glob/prefix guard does **not** fire | ✓ |
| guard message made accurate (no longer "only plain branch names") | both messages now state: `:`-delete / `+`-force prefixes **and** `*` glob are rejected; plain names + simple `src:dst` accepted | ✓ |

Out-of-scope items (per plan) correctly untouched: simple `src:dst` not further constrained, no `remote`-side change, the P6.5 `:`/`+`/banned-flag/configured-remote checks left intact.

### P6.9-109 — apply_edit `.git/`-deny + ADR-036 D3-i amendment + t11 (`mutation_tools.py:172-177`)

The deny is correctly placed: **after** `dest = _check_path(...)` (so it checks the **resolved** path, symlinks followed) and **before** `dest.parent.mkdir` / temp-create / write — so a denied call mutates nothing (no dir created, no temp written, file unchanged).

| Dispatch / acceptance item | Evidence | ✓ |
|---|---|---|
| any `.git/` path → `LocalToolError` (only `.git/`, not over-broad) | `parts = dest.relative_to(resolved_root).parts; if parts and parts[0] == ".git":` — denies `.git`, `.git/config`, `.git/hooks/pre-push`; `parts` truthiness guards the root-itself (`parts==()`) edge against `IndexError` | ✓ |
| check is apply_edit-local, NOT in `_check_path` (read tools unaffected) | `local.py` is **not** in the diff; the deny lives in `_apply_edit` only — `read_file`/`list_files` keep reading `.git/` (harmless; only the write is the poison vector) | ✓ |
| resolved-dest ⇒ in-sandbox symlink-into-`.git/` also denied | because `dest` is post-`_check_path` (`.resolve()`), `apply_edit("symlink_to_dotgit/config")` resolves under `.git` ⇒ denied. Defense beyond the literal-path case. | ✓ |
| `.git/config` denied **and file unchanged** | t11 + `test_apply_edit_git_config_denied` assert both `LocalToolError` and `read_text()=="[original]"` | ✓ |
| `.git/hooks/pre-push` denied (whole-`.git/`, not just config) | `test_apply_edit_git_hooks_denied` | ✓ |
| normal workspace write still succeeds (deny not over-broad) | `test_apply_edit_git_deny_not_over_broad` + the t11 `workspace.txt` case | ✓ |
| ADR-036 D3-i carve-out wording accurate | D3-i bullet annotated `[Annotated P6.9 2026-06-15: …"contained-in-root ⇒ writable, *except* the control-plane .git/"…apply_edit-local…deny scope = .git/ only]`; residuals row at `:138` also annotated; house `[Annotated …]` style; cross-ref to D3-iii @ line 75 (the exfil-by-remote residual where the #109 caveat lives) is valid — annotations are single-line replacements, line numbers do not shift | ✓ |
| **t11 updated + load-bearing (revert ⇒ t11 FAIL)** | see §4 fail-on-revert | ✓ |

t11's existing AST guard (asserts the pinned `O_NOFOLLOW`/`os.open` write recipe) is unaffected — the new deny block adds no `os.open`/`O_NOFOLLOW` text; the AST walk + fallback substring check still pass.

Ratified out-of-scope items correctly **not** implemented: `.hg`/`.svn` (git-only), operator-configurable in-root denylist (YAGNI), case-insensitive `.GIT` (see §5).

## 3. Constitutional / spine / ADR

- **Spine byte-frozen.** Grep over the `+` side of the diff for `LLMPurpose | _execute_local_call | autonomy | gate | confirm_then | _SUBPROCESS_TOOL_NAMES | _NETWORK_TOOL_NAMES` → **no additions.** No change to `_execute_local_call`, the autonomy gate, or the confirm-then-execute machinery. Both atoms are pure tool-boundary input-validation / containment tightening.
- **No new `LLMPurpose`** — none in the diff (content-gen surfaces only invariant holds).
- **No new ADR.** ADR-036 amended in place (D3-i bullet + residuals row); `plan_has_adr=false` is correct — this is an amendment to the already-Accepted ADR-036, the architect's brief ratification is the bless, no separate Accept gate. The amendment IS inscribed with the dated marker (audit-trail discipline satisfied).

## 4. Gates (independent) + fail-on-revert

Isolated worktree @ 78d00fe, `uv sync --all-extras`:

- `ruff check .` → **All checks passed**
- `ruff format --check .` → **313 files already formatted**
- `mypy` → **Success: no issues found in 310 source files**
- `pytest -q` (full suite) → **rc=0**, all-pass. (Two pre-existing benign warnings unrelated to this diff: fastapi/starlette `httpx` deprecation, and a `test_net_trust.py` DNS-timeout background-thread `PytestUnhandledThreadExceptionWarning` — both in untouched surfaces; neither affects exit code.)
- Target-suite baseline (t11, t12, `test_mutation_tools.py`, `test_subprocess_tools.py`) → 61 tests, rc=0.

**Fail-on-revert — both atoms verified** (guard surgically neutered via `if False and …`, then restored via `git checkout`):

- **P6.9-110** (neuter `if "*" in branch`): rc=1; **FAILED** `test_t12_git_push_argv_discipline`, `test_git_push_glob_refspec_rejected`, `test_git_push_glob_star_alone_rejected`, `test_git_push_glob_in_src_dst_rejected`. The message-reword tests (`…refspec_delete_rejected`, `…force_push_rejected`) and the no-over-block test (`…simple_src_dst_not_over_blocked`) stayed **green** — proving each guards its own invariant independently of the `*` block.
- **P6.9-109** (neuter `if parts and parts[0] == ".git"`): rc=1; **FAILED** `test_t11_apply_edit_write_containment` (failing assertion is exactly `t11: .git/config write should have been denied` — the dispatch-pinned requirement), `test_apply_edit_git_config_denied`, `test_apply_edit_git_hooks_denied`. `test_apply_edit_git_deny_not_over_broad` and all pre-existing apply_edit containment tests (traversal / symlink / oversize / atomic) stayed **green** — the deny is load-bearing and not over-broad.

## 5. Non-blocking observations (🟢 — no routing needed)

- **🟢 #110 first-message redundancy (polish).** The `:`/`+`-prefix branch's message names `(: delete / + force)` twice ("uses a refspec prefix (: delete / + force); refspec prefixes (: delete / + force) and glob (*) refspecs are rejected; …"). Accurate, just verbose; the `*`-branch message has no duplication. Cosmetic — leave or trim in a future hygiene pass.
- **🟢 #109 case-insensitive `.GIT` residual (ledger).** The deny matches the literal resolved component `.git`; on a case-insensitive FS (macOS/Windows default) `.GIT/config` may bypass depending on `.resolve()` case-canonicalization. This is **ratified out of scope** (senior plan §"Out of scope": "do not implement; note as residual if you wish") — the junior chose not to inscribe a residual note. Within latitude; flagging only for ledger completeness should a future cross-platform pass want it in ADR-036's residuals.

## 6. Verdict

**`clean`.** Implementation is faithful to the brief + senior plan + architect ratification (#110 routine-α; #109 direction (a), `.git/`-only, D3-i in-place amendment). Spine frozen, no new ADR/`LLMPurpose`, independent gates green, fail-on-revert proven for both atoms. → Feeds the architect's synthesis alongside R0-B (running in parallel) and the senior plan-vs-impl review; no architect routing decision is raised by this R0-A.
