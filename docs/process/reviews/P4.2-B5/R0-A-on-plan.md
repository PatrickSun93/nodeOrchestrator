---
task_id: P4.2-B5
stage: R0-A-on-plan
lens: single (requires_cross_family_review=false, architect-ratified)
reviewer: architect-partner
date: 2026-06-05
verdict: needs_architect
summary: >
  Plan + ADR-036 FAITHFULLY implement all 5 ratified brief decisions; the threat
  posture is sound and the reuse claims verify against origin/main. needs_architect
  is for ROUTING (push-backs 1 SSH_AUTH_SOCK + 2 email-transport gate B5-2/B5-3) and
  the ADR-036 Accept moment — NOT for any plan defect. Two impl-precision watch-items
  carried to R0-A-on-impl (Y1 apply_edit write-recipe coherence; M-2 trusted-output echo).
---

# R0-A on plan — P4.2-B5 (mutation local tools)

**Method.** Verify-cite against `origin/main` (working tree byte-identical to `origin/main`
for every source file cited — confirmed via `git diff --stat origin/main` over
`tools/`, `agents/selection.py`, `mcp/subprocess_trust.py`, `api/app.py`,
`tests/tools/test_constitution.py`, `config/tools.yaml`; the only diff vs `origin/main`
is the plan, ADR-036, and the `.workflow` yaml — no ui/* noise on this branch).
Single-lens: I carry the plan-stage weight alone, so the threat-probe below is sharp.
State-machine self-check: `awaiting_architect_accept`, no pre-existing R0-A-on-plan — clean.

---

## 1. Faithfulness of the 5 ratified decisions (the core ask — do NOT re-litigate)

All five are implemented faithfully. Cites below.

**D1 — 3 true mutations; `propose_edit` OUT.** FAITHFUL. Plan B5-1/2/3 implement
`apply_edit`/`send_email`/`git_push`; `propose_edit` is OUT (plan:33 out-of-scope,
plan:91 "remains deferred"; ADR-036 D1 ¶2). `tools.yaml` revs match the plan's claims
(`tools.yaml:32` apply_edit rev 2, `:48` send_email rev 3, `:50` git_push rev 1,
`:30` propose_edit rev 5). ✓

**D2 — gate-owned tier / confirm-only-actuates / executor tier-agnostic / NO never-AUTO
floor / NO executor override.** FAITHFUL, and verified against code, not just prose:
- Executor is genuinely tier- and tool-agnostic: `_execute_local_call` (`executor.py:385-435`)
  does `impl = local_tools.get(tool_name)` → miss = `not_implemented` (`:397-411`), hit =
  run. Adding the three to their registries actuates them with a byte-unchanged executor.
- Confirm only actuates: `_confirm_on_writer` reconstructs a real `TOOL_CALL` from the
  persisted `ToolCallPendingMeta` — `tool_name`/`params`/`author` from the gate-produced
  record, **never from the request** (`app.py:595-609`) — then invokes the existing
  `execute_pending_tool_calls([that call], … local_tools=ctx.local_tools …)` (`:617-624`).
  B5 adds zero confirm/endpoint code; it populates the registry. ✓
- A COUNTDOWN/HARD call does not auto-fire in-turn: the turn-loop executor filters
  `EventType.TOOL_CALL` only (`executor.py:108`), so a `TOOL_CALL_PENDING` is skipped. ✓
- AUTO-under-intent edge accepted, not floored: ADR-036 D2 ¶4 carries it as an honest
  ACCEPT and explicitly forbids an executor-side "mutations always confirm" override
  (carry-forward #1, ADR-036 §⭐⭐.1 / D2 ¶3). The plan reaffirms the never-AUTO floor OUT
  (plan §5 push-back 5). No special-case is added. ✓

**D3 — git_push ambient/local-auth only; NO new secret in scoped_env.** FAITHFUL —
mechanism verified. `scoped_env(extra_env=…, api_key_env=…)` (`subprocess_trust.py:74-96`)
injects a secret **only** when `api_key_env` is passed; the plan's
`scoped_env(extra_env={SSH_AUTH_SOCK})` passes **no** `api_key_env` → no secret, and real
secrets remain stripped (env = `_SAFE_ENV_KEYS` ∪ `extra_env`). `HOME` is in
`_SAFE_ENV_KEYS` (`:51`), so credential.helper + on-disk SSH keys already work under
`scoped_env`; `SSH_AUTH_SOCK` (a unix-socket path, not a credential value) is the one
named non-secret overlay (plan B5-3; ADR-036 D3-iii). Real-credential (PAT/token) push
stays deferred (ADR-036 D3-iii, Considered-alternatives ¶4). ✓ *(Whether to include the
passthrough at all is push-back 1 — §3 below; the mechanism injects no secret either way.)*

**D4 — organize-by-substrate.** FAITHFUL. `send_email` → `network_tools.py` +
`_NETWORK_TOOL_NAMES` (plan B5-2; ADR-036 D4); `git_push` → `subprocess_tools.py` +
`_SUBPROCESS_TOOL_NAMES` (plan B5-3; ADR-036 D4); `apply_edit` → in-process
`mutation_tools.py` (plan B5-1; ADR-036 D4). Both name-sets feed the output-untrusted
union (`selection.py:119-147`), each drift-guarded (`test_constitution.py:558` b35,
`:652` b46) — adding a registry entry without the name-set add fails the sync-test, a
forcing function, not a new test. ✓ The recipient-allowlist + exfil residual are inscribed
(ADR-036 D3-ii). ✓

**D5 — new ADR-036 + amend ADR-028 D3.** FAITHFUL. ADR-036 exists, Status **Proposed**,
RC-23 (stays Proposed until architect Accept; never self-accepted — ADR-036 Status line).
The ADR-028 D3 file edit is sequenced to B5-6 and **gated on Accept** (plan:84,105;
matches the B3/B4 precedent of inscribing-at-impl). That is correct sequencing, not a gap.
ADR-030/034/035 cross-refs are scoped into B5-6. ✓

---

## 2. Threat-probe (the sharp single-lens carry)

**apply_edit WRITE containment — sound posture, one impl-precision gap (→ Y1).**
`_check_path` (`local.py:120-135`) does `(root / path).resolve().relative_to(root)`;
`.resolve()` follows **all** symlinks (parent and final), so at check time it already
rejects traversal, absolute paths, parent-symlink-escape, **and** an existing escaping
final-component symlink (`relative_to` raises → `LocalToolError`). That is genuinely
stricter than the read posture and covers the escaping-symlink cases by itself. The
residual the plan's `O_NOFOLLOW` is actually buying is the **TOCTOU** window (a symlink
planted between check and write) — worth stating precisely, because the plan's recipe is
internally ambiguous on this point (see Y1). Bounded-content (`MAX_RESULT_BYTES` on input
before write) and atomic temp+`os.replace` are both straightforward. Against B5's
in-tool threat model the containment is airtight: the LLM has **no** symlink-creation
primitive in the B5 surface (`apply_edit` writes regular files via `os.replace`;
`git_push` does not checkout), so the parent-component TOCTOU race needs a concurrent
external FS writer — correctly inside the named `RB-FS` residual P4.3 retires
(ADR-036 Reversibility D3-i). This should be inscribed explicitly: `O_NOFOLLOW` is
**final-component only**; parent-component TOCTOU rides `RB-FS`.

**git_push — clean.** argv-never-shell is genuinely free: `t9`
(`test_constitution.py:477-550`) `ast.walk`s the entire `subprocess_tools.py`, so
`git_push`'s argv is covered the moment it lands there. `t9` does **not** inspect argv
*contents*, so the `--force`/`--mirror`/`--delete` ban genuinely needs the new `t12`
(plan B5-5 — correct that it is not free). Flag-shaped `remote`/`branch` rejection
(values starting `-`) + fixed argv `["git","push",<remote>,<branch>]` is the right shape
(plan B5-3). Remote output joins `_SUBPROCESS_TOOL_NAMES` (untrusted) free via the b35
drift test. Per-tool timeout add to `_SUBPROCESS_TIMEOUTS` (`subprocess_tools.py:32-38`)
is needed and named (plan B5-3). ✓

**send_email — clean.** The `web_search` shape keeps the key to the provider header only
(`network_tools.py:211`, `X-Subscription-Token`; never logged/echoed/in output) and
fail-closes when unconfigured (`:191-192`). `send_email` mirrors this (plan B5-2;
ADR-036 D3-ii). One honest shape-difference to note: `web_search` **hardcodes** the
endpoint (`_BRAVE_SEARCH_BASE_URL`, `:48`) whereas `send_email` reads `endpoint` from
`config/email.yaml`. That is still operator-trusted and is **not** in the `{to,subject,body}`
param allowlist, so SSRF stays N/A (agent cannot redirect the endpoint). The recipient is
the exfil vector; allowlist-before-send + the honest exfil-by-recipient residual are
inscribed (ADR-036 D3-ii). ✓

**Carry-forwards — verified, not just asserted.** Empty-executor-diff is achievable: all
three ride `_execute_local_call` unchanged; caps live in the loop (`executor.py:181-249`)
— `git_push` (subprocess marker) → subprocess cap, `send_email` (network marker) →
network cap, `apply_edit` (no marker) → plain in-process `else` (`:240-249`), like
`read_file`. No new `LLMPurpose`: `t3` (`:173`) covers all of `tools/`, so `mutation_tools.py`
is free. t6/t8 (`:344`/`:446`) scan **only** `local.py` → untouched (apply_edit lives in
`mutation_tools.py`). t1/t4 hold (confirm-reconstructed `TOOL_CALL` is the ADR-030
second appender, already guarded). ✓

---

## 3. Findings + the 5 senior push-backs (architect routes; I do not)

**Y1 (🟡 impl-precision — for R0-A-on-impl, not a plan blocker): the apply_edit
write-recipe is internally ambiguous.** Plan B5-1 + ADR-036 D3-i prescribe BOTH
"`O_NOFOLLOW` on the final write target" AND "atomic temp file + `os.replace`". These are
two different strategies with different final-symlink semantics: with temp+`os.replace`,
the destination is **never opened** — `os.replace` replaces a final-component symlink
rather than `O_NOFOLLOW`-failing on it, so `O_NOFOLLOW` belongs on the temp *create*
(`O_CREAT|O_EXCL|O_NOFOLLOW`), and the destination-symlink case is handled by
`_check_path` (existing escaping symlink → rejected at check) + `os.replace` semantics
(in-sandbox symlink → replaced/destroyed, not followed, not "refused"). The plan's
acceptance criterion "final-symlink-escape → refused (`LocalToolError`)" is satisfied by
`_check_path` for an *existing* escaping symlink, but the `t11` AST guard ("uses
`O_NOFOLLOW`, never a plain `open(final,'w')`") must assert the invariant the **chosen**
strategy actually upholds — if the impl uses temp+`os.replace`, there is no
`open(final,'w')` to ban and `O_NOFOLLOW` lives on the temp create. The junior needs one
coherent recipe; R0-A-on-impl must verify the impl + `t11` match. Surfaced now so the
sharp probe lands at impl with the strategy pinned.

**M-2 (minor / forward-watch): apply_edit is the first TRUSTED-output tool that echoes
agent-controlled bytes into the steering excerpt.** Its output `wrote N bytes to <rel
path>` (plan B5-1) is trusted (not in any `_*_TOOL_NAMES` set), so it renders raw into
`_render_snapshot_excerpt` (`selection.py:150-193`, `[<type>] <author>: <content>`). The
`<rel path>` is agent-chosen; a crafted filename with embedded newlines could forge
excerpt lines that mimic another author/type. This is **not** B5-introduced — `log_event`
(`local.py:339-358`) already echoes agent `content` into a trusted excerpt-rendered
result — but `apply_edit` widens the surface to a second such tool. Forward-watch: a
future excerpt-render sanitization (newline-escape on trusted content) covers both; not a
B5 blocker.

**The 5 senior push-backs — which need architect routing:**

- **Push-back 1 (⭐⭐ `SSH_AUTH_SOCK` passthrough) → NEEDS ROUTING.** This gates B5-3
  acceptance and is the single-lens swing factor the brief named. The mechanism is sound
  (no secret injected; real secrets stripped — §1 D3). The *policy* call — include the
  `SSH_AUTH_SOCK` ssh-agent overlay now (a named, non-secret widening of B3's
  strip-everything posture) vs HOME-only on-disk auth — is yours. It sits inside ratified
  decision 3's "ambient/local-auth only, no new secret" envelope (a socket path is not a
  secret), but it widens the c2 boundary, so the senior is right to surface it for explicit
  ratification. My lean: option (a) include — consistent with decision 3, ssh-agent is the
  dominant dev auth, no secret value crosses. You route.

- **Push-back 2 (⭐ email transport shape) → NEEDS ROUTING.** This gates B5-2 acceptance
  and was **not** pinned by the brief (the brief said "SMTP/API, reuse the web_search
  shape" without choosing). Options: (a) config-driven generic HTTP mirroring `web_search`
  [senior lean + mine — leanest, reuses the verified shape, plain `httpx`]; (b) a named
  provider hardcoded like Brave; (c) raw SMTP via `smtplib` (different shape, doesn't reuse
  `web_search`). Sub-call: allowlist shape — explicit recipient list vs `allowed_domains`
  vs both. You route.

- **Push-back 3 (`apply_edit` placement: `mutation_tools.py` vs `local.py`) → senior call,
  no routing required.** Per brief decision 4, architect ratification was required only
  "if it's a constitution-test change". The senior chose `mutation_tools.py` **specifically
  to avoid** a constitution change (t6/t8 stay `local.py`-pristine, verified §2). So the
  choice stays within the senior's delegated authority and triggers no ratification. Flagged
  for your awareness; confirm only if you'd prefer the `local.py`-write carve-out.

- **Push-back 4 (`send_email` output conservative-include) → ratified/mechanical, no
  routing.** Adding `send_email` to `network_tools.py` auto-includes it in
  `_NETWORK_TOOL_NAMES` via the b46 drift test — conservative-include by construction,
  consistent with ratified decision 4. Proceeding as inscribed.

- **Push-back 5 (never-AUTO floor reaffirm OUT) → ratified OUT, no routing.** Ratified
  decision 2 keeps the floor out; the plan correctly keeps it out (a floor would re-open
  the P1.3 `hard_guards.py` placeholder — a separate autonomy slice). This is a checkpoint,
  not a new decision; re-open only if you now want to initiate that scope change.

---

## 4. Verdict

**needs_architect** — for routing (push-backs 1 + 2, which the plan itself states gate
B5-2/B5-3: plan:107) and the **ADR-036 Accept** moment (RC-3/RC-23 — architect-only; B5-6
is gated on it). The plan and ADR-036 are otherwise **sound and faithful**: all 5 ratified
decisions are implemented as ratified, every reuse/free-coverage claim verifies against
`origin/main`, and the threat posture is airtight against B5's in-tool model. No blocking
plan defect. Y1 (apply_edit write-recipe coherence + `t11` invariant) and M-2 (trusted
output echo) are carried to R0-A-on-impl as the sharp probe's watch-items, not plan gates.

**Expected next architect action:** route push-backs 1 + 2 → Accept ADR-036 → dispatch
junior B5-1..B5-5 (B5-6 after Accept). Single-lens impl review = R0-A only, with the Y1
write-containment probe pinned.
