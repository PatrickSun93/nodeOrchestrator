---
task_id: P6.9
review: R0-B (cross-family, requires_cross_family_review=true)
reviewer: r0b (DeepSeek, security lens — subprocess/edit surface, same lens that caught P6.5 refspec bypass)
verdict: approved
impl_ref: origin/claude/P6.9-impl @ 78d00fe (b1d78d4 P6.9-110, 78d00fe P6.9-109)
plan_ref: docs/process/senior-plans/P6.9.md
constitution: spinal gate zero-diff across _execute_local_call / gate.py / LLMPurpose / autonomy / COUNTDOWN spine
bypass_tested: exhaustive (case, symlink, path-normalization, glob variants, refspec edge cases)
findings_count:
  red: 0
  yellow: 0
  green: 4           # two atoms × 2 (security-posture + non-regression)
notes_count: 3        # NN-2 macOS case-insensitive edge, NN-3 nested-.git delimitation, NN-4 literal-* branch false-positive
---

# P6.9 R0-B — Security review: git_push glob-reject (#110) + apply_edit `.git/`-deny (#109)

**Verdict: APPROVED.** Both atoms close their respective config-poisoning /
multi-branch-push vectors at the right defense layer, with zero spine touch,
zero new `LLMPurpose`, zero read-tool regression. Exhaustive bypass search
(attacker-perspective) found no practical escape. Three non-blocking
observations noted.

---

## Security posture recap

These two atoms are the final follow-ons from the P6.5 subprocess refspec
hardening (where R0-B caught `ext::` / `fd::` / inline-URL / `:`/`+` prefix
bypass vectors). The residual windows being closed here:

| Vector | How | Atom | Defense layer |
|---|---|---|---|
| Agent writes `.git/config` to inject attacker remote → exfil on next push | `apply_edit` path to `.git/` | #109 | In-process deny (pre-write, post-`_check_path`) |
| Agent pushes all branches (* glob) to configured remote, enumerating workspace | `git_push` glob refspec | #110 | Input-validation guard (pre-argv-build) |

Both are additive to the existing P6.5 layered defense (configured-remote-only,
banned-flags, `:`/`+` prefix reject, `GIT_ALLOW_PROTOCOL` transport allowlist).
They don't replace or weaken any existing layer.

---

## 🟢 G1 — #110 glob (`*`) reject: bypass search EXHAUSTED

**Code:** `subprocess_tools.py:439-448` — `if "*" in branch:` guard after `:`/`+` prefix checks, before argv build.

### Bypass vectors tested (attacker-perspective)

| Vector | Payload | Result | Why |
|---|---|---|---|
| `*` glob (both sides) | `refs/heads/*:refs/heads/*` | REJECTED | `*` in string |
| Bare `*` | `*` | REJECTED | `*` in string |
| Glob src only | `*:main` | REJECTED | `*` in string |
| Glob dst only | `main:*` | REJECTED | `*` in string |
| Tag glob | `refs/tags/*:refs/tags/*` | REJECTED | `*` in string |
| `?` wildcard | `refs/heads/?:refs/heads/?` | ACCEPTED (not a bypass) | `?` is NOT a git glob character — git refspecs only interpret `*`. Shell glob `?` has no meaning to git. |
| Char class `[ab]` | `refs/heads/[ab]:refs/heads/[ab]` | ACCEPTED (not a bypass) | `[ab]` is NOT a git glob character — shell-only. |
| Unicode lookalike `∗` (U+2217) | `main∗other` | ACCEPTED (not a bypass) | Unicode asterisk operator ≠ ASCII `*` (U+002A). Git does not interpret it. |
| Unicode lookalike `⁎` (U+204E) | `main⁎other` | ACCEPTED (not a bypass) | Same — not ASCII `*`. |
| Simple `src:dst` | `main:other` | ACCEPTED ✓ | No `*`, no `:`/`+` prefix. Explicitly allowed per plan AC. |
| Fully-qualified src:dst | `refs/heads/main:refs/heads/other` | ACCEPTED ✓ | Same. |
| Plain branch | `main` | ACCEPTED ✓ | Baseline. |
| Delete refspec `:main` | `:main` | REJECTED ✓ | `:` prefix guard (P6.5) fires first. |
| Force-push `+main:main` | `+main:main` | REJECTED ✓ | `+` prefix guard (P6.5) fires first. |
| Flag injection `--all` | `--all` | REJECTED ✓ | `-` prefix guard (P6.5) fires first. |
| Literal `*` in branch name | `fix-*-bug` | REJECTED (false positive) | Architect-accepted limitation — `*` is ambiguous between literal branch char and glob operator; blanket ban is safer than parsing. |

### Verdict

No practical bypass. Git's refspec glob vocabulary is exactly `*` (one character); the blanket substring check closes it completely. The `?` / `[ab]` / Unicode paths don't expand the attack surface because git doesn't interpret them as globs. The literal-`*` false positive is a known YAGNI tradeoff (no real branch uses `*` in its name).

**simple src:dst non-regression verified** — `test_git_push_simple_src_dst_not_over_blocked` pushes `main:other` to a bare repo; the guard does NOT fire.

---

## 🟢 G2 — #109 apply_edit `.git/` deny: bypass search EXHAUSTED

**Code:** `mutation_tools.py:168-178` — `parts = dest.relative_to(resolved_root).parts; if parts and parts[0] == ".git": raise LocalToolError(...)`.

The check is apply_edit-local (not in `_check_path`), post-resolve, pre-write, **first-component-only** (`parts[0]`). Read tools are unaffected.

### Bypass vectors tested (attacker-perspective)

#### Direct paths

| Vector | Payload | Result | Why |
|---|---|---|---|
| `.git/config` | `.git/config` | BLOCKED | `parts[0] == ".git"` |
| `.git/hooks/pre-push` | `.git/hooks/pre-push` | BLOCKED | Same |
| `.git` (dir or submodule file) | `.git` | BLOCKED | `parts[0] == ".git"` |
| `.git/` (trailing slash) | `.git/` | BLOCKED | `.resolve()` normalizes |

#### Case-sensitivity

| Vector | Payload | Linux result | macOS (case-insensitive) result |
|---|---|---|---|
| `.GIT/config` | `.GIT/config` | ALLOWED — **NOT a bypass**: `.GIT` ≠ `.git` on case-sensitive FS; git ignores `.GIT` | If `.git` exists: BLOCKED (`.resolve()` normalizes to on-disk case `.git`). If `.git` absent: ALLOWED — but no repo exists to poison ([[#NN-2-macos-case-edge]]) |
| `.Git/config` | `.Git/config` | ALLOWED (same reasoning) | Same as above |
| `.gIT/config` | `.gIT/config` | ALLOWED (same reasoning) | Same as above |

#### Path normalization

| Vector | Payload | Result | Why |
|---|---|---|---|
| Dot-slash | `./.git/config` | BLOCKED | `.resolve()` collapses `.` |
| Dot-dot normalization | `.git/../.git/config` | BLOCKED | `.resolve()` collapses `..` |
| Parent traversal | `subdir/../.git/config` | BLOCKED | `.resolve()` collapses |
| Double slash | `.//.git/config` | BLOCKED | `.resolve()` normalizes |
| Absolute path | `/root/.git/config` | ESCAPE (caught by `_check_path`) | `relative_to()` raises before `.git/` check |

#### Symlink-based

| Vector | Setup | Payload | Result | Why |
|---|---|---|---|---|
| Symlink → `.git` | `link-to-git → .git` | `link-to-git/config` | BLOCKED | `.resolve()` follows symlink → canonical path has `.git` as first component |
| Parent-dir symlink | `sub/link → ../.git` | `sub/link/config` | BLOCKED | Same — `.resolve()` normalizes through symlink |
| Symlink when `.git` absent | `link → .git` (target doesn't exist) | `link/config` | BLOCKED | `.resolve()` resolves symlink → `root/.git/config` → parts[0] = `.git` |

Symlink bypass is fully closed by `_check_path`'s existing `.resolve()` — no new logic needed.

#### Substring vs prefix (non-regression — must NOT block)

| Vector | Payload | Result | Why |
|---|---|---|---|
| Dotfile with `.git` substring | `.gitignore` | ALLOWED ✓ | `parts[0] = ".gitignore" ≠ ".git"` |
| File with `.git` mid-name | `my.gitignore` | ALLOWED ✓ | `parts[0] = "my.gitignore" ≠ ".git"` |
| Extension-like | `foo.git.txt` | ALLOWED ✓ | `parts[0] = "foo.git.txt" ≠ ".git"` |
| End-of-name `.git` | `foo.git` | ALLOWED ✓ | Single component, `"foo.git" ≠ ".git"` |
| Multi-component with `.git` substring | `some.git.file` | ALLOWED ✓ | Same |

#### Nested `.git` (non-first component)

| Vector | Payload | Result | Why |
|---|---|---|---|
| Submodule `.git` file | `subdir/.git` | ALLOWED — [[#NN-3-nested-git-delimitation]] | `parts[0] = "subdir"`. Only root `.git/` protected. |
| Nested git dir | `a/.git/config` | ALLOWED — same | Design choice: protect workspace-root control plane, not submodule internals. |
| Deep nesting | `a/b/.git/hooks` | ALLOWED — same | Same. |

### Verdict

No practical bypass for the workspace-root `.git/` control plane. The check sits at the right layer (apply_edit-local, post-resolve, pre-write), catches all normalization and symlink tricks via `_check_path`'s existing `.resolve()`, and correctly avoids over-blocking legitimate files containing `.git` as a substring. The first-component-only scope is a deliberate design choice (not an oversight) — nested `.git/` directories are submodule concerns, not workspace-root config-poisoning vectors.

**Non-regression verified** — `workspace.txt` write succeeds; `.gitignore`/`my.gitignore`/`foo.git.txt` all pass.

---

## 🟢 G3 — Spine constitutional: ZERO diff

```
$ git diff origin/main...origin/claude/P6.9-impl -- \
    src/orchestrator/core/gate.py \
    src/orchestrator/autonomy/ \
    src/orchestrator/llm/llm_purpose.py \
    src/orchestrator/rooms/ \
    src/orchestrator/skills/ \
    src/orchestrator/agents/
→ (empty)
```

- `_execute_local_call` gate: byte-frozen
- `LLMPurpose`: zero new enum values or call sites
- Autonomy `confirm_then_execute`: untouched
- COUNTDOWN spine: untouched
- `_check_path` (`local.py`): untouched — the `.git/` deny is apply_edit-local as planned

**6 files changed, all within plan scope**: `mutation_tools.py` (+11), `subprocess_tools.py` (+10/-1), `ADR-036` (+4 annotated), `test_constitution.py` (+56), `test_mutation_tools.py` (+44), `test_subprocess_tools.py` (+62/-2).

---

## 🟢 G4 — Gate execution: ALL GREEN

Independent gate run on detached worktree @ 78d00fe with `uv sync --all-extras`:

| Gate | Result |
|---|---|
| `ruff format --check` (5 files) | 5 already formatted ✓ |
| `ruff check` (5 files) | All checks passed ✓ |
| `mypy` (2 source files) | Success: no issues found ✓ |
| `pytest tests/tools/{constitution,mutation,subprocess}` (82 tests) | 82 passed ✓ |
| `pytest tests/` (full suite, 2579 tests) | 2579 passed, 0 failed ✓ |

Full-suite warnings: 2 pre-existing (Starlette deprecation, net_trust DNS timeout test). Zero new warnings.

---

## Notes (non-blocking)

### NN-2 — macOS case-insensitive FS edge (`.GIT` when `.git` absent)

On macOS APFS/HFS+ (case-insensitive): if `.git` does NOT exist, `Path(".GIT/config").resolve()` returns `/root/.GIT/config` (no on-disk inode to normalize against). The check `parts[0] == ".git"` misses because `parts[0] = ".GIT"`. However, this requires `.git` to be absent (no git repo → nothing to poison). Once `.git` exists, `.resolve()` normalizes to the on-disk case and the check catches it. **Practical risk: negligible.** If the product later targets macOS as a first-class sandbox host, consider `path_str.lower()` or `os.path.realpath()` case-normalization. Not action-worthy today — the sandbox host is Linux.

### NN-3 — Nested `.git/` delimitation

Only `parts[0] == ".git"` (root `.git/`). Nested `.git` directories (`subdir/.git/config`, submodule `.git` file) are not blocked. This is a deliberate scope choice per the plan (deny root workspace control plane only, not submodule internals). The primary exfil vector (origin remote in `.git/config`) lives at the workspace root; submodule `.git` poisoning would require git-init'd submodules and agent-triggered submodule operations — neither exists in the current tool surface. **Limitation is acceptable for the current threat model.** Documented here so it's not rediscovered as a "missed bypass."

### NN-4 — Literal `*` in branch names is falsely rejected

`fix-*-bug` → REJECTED by `"*" in branch`. Git allows `*` in branch names (it's a legal ref character), and the blanket substring check can't distinguish literal `*` from glob `*` without refspec parsing. Architect accepted this tradeoff (see brief ratification). **Real-world impact near-zero** — branches named with literal `*` are vanishingly rare.

---

## Cross-reference: plan-vs-impl findings

Plan-vs-impl (senior) verdict: **clean** — 0 red, 0 yellow, 2 green. Both atoms atomic-faithful to `senior-plans/P6.9.md`. NN-1 (cosmetic message redundancy) noted — non-blocking; R0-B concurs.

---

## Recommendation

**APPROVE → merge.** No blocking security findings. Both atoms close their respective config-poisoning / multi-branch-push vectors at the correct defense layer. Exhaustive bypass search found no practical escape. Spine byte-frozen. All gates green (2579/2579). Three non-blocking observations (NN-2/3/4) documented for forward-watch.
