# ADR-034: Subprocess local tools — execution posture, threat model, honest residual

**Status:** Proposed — 2026-06-05

**Scope:** The execution posture, four-sub-surface threat model, honest FS/network residual, and executor placement for the five deferred **subprocess** local tools (`run_tests` / `run_lint` / `git_blame` / `git_log` / `git_diff`) — shipped **before** the P4.3 syscall sandbox, reusing the ADR-031 D2 subprocess-trust seam. Amends ADR-028 D3 (these five no-longer-deferred).

---

## Context

P4.1 (ADR-033) closed the in-turn investigation loop: an agent can `read_file` → `search_text` → `find_references` and **re-dispatch** on the result, all within one turn. But every tool P4.1 can chain is **in-process and read-only** (`os.walk` + `re`); ADR-033 ⭐⭐ carry-forward #6 **explicitly forbade** shelling out, deferring the subprocess surface to this slice. So today an agent **cannot run the tests it is trying to fix**, lint the code it is editing, or read the git history that explains a line — the flagship bug-fix / code-review loop's *"re-investigate on a failed test"* step (P4-roadmap §7) has nothing subprocess-shaped to call.

ADR-028 D3 deferred these five as *"a subprocess surface, the c2 env-leak class … Each distinct surface (network / subprocess / mutation) warrants its own slice + classification review."* This is that slice. The runtime already has the seams: the executor's Posture-B `LocalToolFn` cap path (ADR-031 D1, `executor.py:158-202`) and the subprocess-trust machinery (`mcp/subprocess_trust.py` — `build_scoped_env`, kill-no-orphan, the LAYER-1 watchdog; ADR-031 D2). B3 is therefore mostly **wiring five fixed-argv commands through reused trust primitives**, plus inscribing the **posture + residual** that makes "shell out, but not yet sandboxed" an *Accepted boundary* rather than an oversight.

The load-bearing tension: B3 ships **before** the P4.3 syscall sandbox (A1). It must run subprocesses inline on the single writer with a **lighter posture** that neutralises the two sharpest subprocess risks (command-injection, env/secret-leak) and restores the ADR-028 D5 liveness bound — while honestly Accepting that the subprocess is **not** syscall-isolated. That residual is **identical in kind to the already-Accepted `RB-FS/NET`** (ADR-031 D1a) and **strictly narrower** (first-party fixed-argv commands over a *trusted* workspace, vs ADR-031's fetched/untrusted plugin code).

---

## ⭐⭐ Constitutional carry-forward (NON-NEGOTIABLE — inscribed, not decided; per P4-roadmap §10)

The senior inscribes; the impl enforces; R0-A/R0-B probe each.

1. **Execution stays DOWNSTREAM of the gate (ADR-028 #1 / t4).** Subprocess tools route the **unchanged** `process_tool_calls` → `emit_gate_decision` path; AUTO (rev 9–10) executes; any `COUNTDOWN`/`HARD` variant appends `TOOL_CALL_PENDING` (no `TOOL_CALL`) → **not executed in-loop** (confirm-then-execute is out-of-band; the turn-loop does not wait for confirm, ADR-033 carry-forward #3). The executor never re-gates.
2. **No LLM judgment in the executor; no new `LLMPurpose` (t2/t3).** The subprocess path is pure code. Subprocess output is **not** interpreted (D3 below) — so no `LLMPurpose` is consumed at all on this path.
3. **The subprocess trust boundary is REAL for env/secret + liveness/DoS, HONEST about FS/network.** Scoped env (no secret/credential leak — the c2 lesson), bounded-timeout + kill-no-orphan + per-turn cap (restores the ADR-028 D5 absolute bound), **but NOT a syscall sandbox** — the `RB-FS/NET`-class residual, Accepted **exactly as ADR-031 D1a modelled it** (D4 below).
4. **Reuse, don't rebuild — one subprocess protocol (ADR-031 D2).** The scoped-env + kill-no-orphan + LAYER-1 watchdog already live in `mcp/subprocess_trust.py`; B3 **consumes** them. No second subprocess mechanism.
5. **`tools/` stays a downstream leaf (t1); `_execute_local_call` stays byte-unchanged** (ADR-031 HR#2 empty-executor-diff): B3 rides the Posture-B `LocalToolFn` path (D5), so the executor's decision path is untouched.
6. **Argv, never shell — test-enforced.** No `shell=True` / no shell-string anywhere; a **constitution test forbids it** in the subprocess builder (the ADR-032 *"constitution test forbids `verify=False`"* precedent applied to command-injection).

---

## Decisions

### D1 — Ship all five subprocess tools; classifications stand

The five ship in B3: `run_tests` (`tools.yaml` rev 9 → AUTO), `run_lint` / `git_blame` / `git_log` / `git_diff` (rev 10 → AUTO). At any agent with `threshold_auto ≤ 9` all five reach `AUTO_EXECUTE`. The classifications are **confirmed as-is** (ADR-028 D3 amendment below).

**Two trust tiers inside the set, both shipped:** the **git-read trio + `run_lint`** *run a known tool that READS/parses* (no project-code execution); **`run_tests` executes the project's own test code** (arbitrary code execution by design — rev 9 already hedges *"side effects rare in well-formed tests"*). Both tiers share one posture (below); `run_tests` carries the largest instance of the FS/network residual because it runs workspace code, not just reads it. The flagship loop needs `run_tests` (*"re-investigate on a failed test"*) **and** git history; once the subprocess machinery exists the marginal cost of the git trio + lint is ~nil.

**Why:** value-first sequencing (P4-roadmap §7); splitting would not shrink the posture work (the residual + the machinery are shared).

### D2 — Execution posture: lighter-inline-now + honest residual (THE load-bearing call)

B3 runs each subprocess **inline on the single writer** with this posture:

- **Allowlisted argv (never shell).** Fixed/templated argv array per tool; **no `shell=True`, no shell-string** (D3-i).
- **Scoped env.** Reuse `subprocess_trust.build_scoped_env` → only `_SAFE_ENV_KEYS` (`PATH`/`HOME`/…); **never** the orchestrator's full `os.environ`; **no** secret/credential/`api_key` keys. B3 tools pass **no** `api_key_env` (they need none).
- **Bounded timeout + kill-no-orphan.** A shared bounded deadline; on timeout the child **process group** is killed (`start_new_session=True` → `pgid == pid`) via the reused `_terminate_subprocess` (SIGTERM → SIGKILL escalation) + `_kill_watchdog` (LAYER-1 orchestrator backstop). Restores the ADR-028 D5 liveness bound.
- **Bounded output.** stdout+stderr truncated at `MAX_RESULT_BYTES` (64 KiB, reused) — the `read_file` bounded-output analog; an unbounded test log cannot OOM the single writer.
- **`cwd` = sandbox root** (the operator-configured workspace, same root as `build_local_tool_registry`).
- **Per-turn cap** (D5) — a fork-exhaustion bound under the P4.1 turn-loop's `(1+N)` passes.

**The honest residual (`RB-FS/NET`-class).** The subprocess is **NOT** syscall-isolated: it runs with the operator process's **FS-read + outbound-network** privilege (it can `open()` `~/.ssh/id_rsa`, `socket()` out). This is **identical in kind to the already-Accepted `RB-FS/NET`** (ADR-031 D1a) and **strictly narrower**: first-party **fixed-argv** commands (`pytest`/`ruff`/`git`) over a **trusted** workspace, vs ADR-031's fetched/untrusted plugin code running arbitrary callables. We **Accept the real surface, not a softened one** (the ADR-031 D1a / ADR-029 D4 discipline).

**Forward-watch (one residual, one retirement path).** P4.3 / A1 builds the real FS/network syscall sandbox. B3's subprocess execution is wired through the **same** `subprocess_trust` entrypoint A1 will wrap — so A1 retires **this** residual and the ADR-031 D1a `RB-FS/NET` residual **together**, on one retirement path, not as a second separately-tracked surface. The scoped-env B3 delivers does **not** reverse when the sandbox lands; the sandbox **wraps** the existing subprocess.

**Considered + rejected — Option B (reorder B3 behind P4.3):** build the syscall sandbox first; subprocess tools run sandboxed from day one (no residual). Rejected: blocks the flagship capability on the heaviest container-orchestration slice; inverts value-first sequencing (§7); the residual is an **Accepted-and-gated class** (ADR-031 D1a), not a new risk.

### D3 — Threat model: four sub-surfaces

**(i) Command-injection → argv, never shell.** `argv` array; **no `shell=True` / no shell-string**; fixed/templated argv per tool (D6); **params constrained** — `run_tests` takes a *sandbox-relative test path*, **not** arbitrary flag passthrough (`-p`/`--pdb`/`-c`/…). The path that enters argv is the **resolved absolute path** from `_check_path` (always under `sandbox_root`, always starts with `/`) — so a path param can never be flag-shaped. git commands additionally place `--` before the path (defence-in-depth against option injection). **Test-enforced** (carry-forward #6).

**(ii) Env-leak → scoped env allowlist.** Reuse `build_scoped_env`; only `_SAFE_ENV_KEYS`; **no** secret/credential/`api_key` keys (the c2 lesson ADR-028 D3 named).

**(iii) Arbitrary-exec-within-perms → the residual** (D2). Accepted honestly; retired by P4.3.

**(iv) Output-as-untrusted — the third trust class (reconciles ADR-028 D2 + ADR-033 D6 / R2-N1).** Subprocess stdout is **external-process output** (a malicious commit message surfaced by `git_log`; attacker-influenced strings printed by `run_tests`; a crafted hunk in `git_diff`) — **NOT** "our own code" output. ADR-028 D2's binary (MCP-untrusted-interpret / local-trusted-raw) therefore gains a **third class: local-but-untrusted → raw, framed, excerpt-excluded.**

- **Render as RAW `TOOL_RESULT` (preserve exact bytes), NOT interpret→`OBSERVATION`.** The agent's value is the **precise bytes** — a stack trace, a diff hunk — to act on; an interpreted summary would *lose* them (and cost an LLM call inside the D5 single-writer block). So unlike MCP results, subprocess results are **not** interpreted; no `OBSERVATION` is produced.
- **Extend the P4.1 excerpt-exclusion filter to subprocess results.** ADR-033 D6 / R2-N1 excludes raw MCP `TOOL_RESULT`s from `snapshot_excerpt` (`agents/selection.py::_mcp_tool_result_call_ids`, `mcp__`-prefix-only) so injected external text cannot steer a re-dispatched agent via the system block. B3 **widens** that exclusion to the five subprocess tools (keyed on the `TOOL_CALL`'s `tool_name`) — the P4.1 Y1 surface, now widened to subprocess.
- **Why excluding from the excerpt does not blind the acting agent.** The re-dispatch loop (`api/app.py:454`) passes the last result-class event of a pass as the **`current_event`** (the user message) of the next pass — a channel **distinct** from `snapshot_excerpt` (the system-block context). The acting agent still receives the raw subprocess bytes via `current_event` and can re-investigate; the exclusion only removes them from the **cross-agent / cross-pass system-block steering surface** (the dangerous injection vector). This is parity with the existing `mcp__` treatment, minus the `OBSERVATION` (rejected above).

**Plus the liveness terms (inscribed, not chosen):** bounded output, bounded timeout + kill-no-orphan, per-turn cap (D2/D5) — each a finite term in the ADR-028 D5 single-writer bound, now multiplied by the turn-loop's `(1+N)` passes (ADR-033 D4).

### D4 — Reuse the ADR-031 D2 subprocess-trust seam (one mechanism)

`subprocess_trust.py` today exposes `build_scoped_env` + an MCP-stdio-JSON-RPC context manager (`subprocess_mcp_stdio`) + the kill machinery (`_terminate_subprocess`, `_kill_watchdog`, `_pgid_kill`). The MCP-stdio manager is **not** reusable as-is for B3 (pytest/ruff/git emit plain bytes, not JSON-RPC). B3 therefore adds **one** new entrypoint to the **same module** — `run_scoped_command(argv, *, cwd, env, timeout_s, max_bytes)` — that **reuses** `build_scoped_env` (via the caller), `start_new_session=True`, `_terminate_subprocess`, and `_kill_watchdog`, adding only the missing capability: **bounded capture of a plain command's stdout/stderr**. This keeps **one subprocess protocol** (ADR-031 D2) — the kill-no-orphan + scoped-env discipline is the reused asset; only the output-shape differs. (See Reversibility: this lightly **extends** the ADR-031 D2 contract — annotated there.)

### D5 — Executor placement: the existing Posture-B `LocalToolFn` path (empty-executor-diff)

Each B3 tool is a **non-`mcp__` local-registry entry** whose `LocalToolFn` launches the subprocess and is marked `_is_posture_b_subprocess = True`. The executor **already** caps such entries (the per-turn subprocess cap) and runs them via the **byte-unchanged** `_execute_local_call` (`executor.py:158-202`). **No executor-decision edit** (ADR-031 HR#2 / ADR-028 D6 empty-executor-diff; t3b). The cap counter — historically `MAX_POSTURE_B_CALLS_PER_TURN` — is **generalised to `MAX_SUBPROCESS_CALLS_PER_TURN`**: it bounds *all* subprocess forks per turn (fetched-plugin Posture-B **and** B3), which is what it always semantically was. The marker ClassVar/attribute name `_is_posture_b_subprocess` is retained (it marks "a subprocess-launching local tool," plugin or B3).

**Result semantics (ride `_execute_local_call` unchanged):** normal completion at **any exit code** → `LocalToolOutput` → `TOOL_RESULT` (a failing test suite / lint finding is *expected output the agent must see*, not a tool failure); timeout-kill / spawn-failure / path-validation-failure → the impl raises → `TOOL_FAILED`. The exit code is reported inside the result content.

**Carry-forward confirmation:** t1 (`tools/` leaf), t2 (no autonomy decision), t3 (no new `LLMPurpose`), t4 (execute-on-`TOOL_CALL`-only) all hold; the gate stays the sole chokepoint, downstream.

---

## Considered alternatives

- **A new explicit subprocess branch in `execute_pending_tool_calls`** (third route beside `mcp__`/local). Rejected: would edit the executor decision path, breaking empty-executor-diff (HR#2); the Posture-B path already provides the cap + run.
- **Interpret subprocess output → `OBSERVATION` (symmetric with MCP).** Rejected (D3-iv): costs an LLM call per result inside the D5 block + a lossy summary the agent often can't act on; the precise bytes are the value.
- **Exclude subprocess results from the excerpt via a `ToolResultMeta.external_output` flag** (producer declares untrust). Rejected for B3: the flag would have to be written by `_execute_local_call` (the sole TOOL_RESULT appender for local tools), violating the byte-unchanged constraint (HR#2). Keying the excerpt exclusion on the `TOOL_CALL`'s `tool_name` (as the `mcp__` prefix already does) needs **no** executor change. A drift guard (constitution sync-test) neutralises the tool-name-list's only weakness.
- **Configurable test/lint runner.** Deferred (see Reversibility): MVP hardcodes `python -m pytest` / `ruff check` (the project's own loop is Python); a config-driven runner is additive later.

---

## Consequences

**Easier:** the flagship bug-fix / code-review loop can actually run (tests + lint + git history mid-investigation); the subprocess machinery + posture exist for B4 (network) / B5 (mutation) to build on; one residual on one retirement path for P4.3.

**Harder:** a real FS-read / outbound-network surface now exists at runtime (the honest residual) until P4.3 — Accepted, gated, narrower than ADR-031's; the single-writer block grows by the subprocess time × `(1+N)` passes (bounded by the cap + timeout); the excerpt-exclusion tool-name list must stay in sync with the subprocess registry (guarded by a sync-test).

**Neutral:** classifications unchanged (rev 9/10 stand); no new `EventType`, no new `LLMPurpose`; `_execute_local_call` byte-unchanged.

---

## Reversibility

| Change | Cost to reverse / evolve |
|---|---|
| The five tools (registry entries + closures) | **Low** — additive; removing an entry returns it to fail-closed `not_implemented`. |
| `run_scoped_command` in `subprocess_trust.py` | **Low–Med** — a new entrypoint in the ADR-031 D2 module; **lightly extends** ADR-031 D2's "one subprocess protocol" (annotate ADR-031 D2 `[Extended P4.2-B3 → ADR-034]`). Reused by B4/B5. |
| `MAX_POSTURE_B_CALLS_PER_TURN` → `MAX_SUBPROCESS_CALLS_PER_TURN` rename | **Low** — mechanical; touches the executor constant/var/error_class + the two plugin test files; marker name retained. |
| **D2 `RB-FS/NET`(B3) residual → P4.3 syscall sandbox** | **Additive (forward-watch)** — B3 delivers env/secret/DoS isolation; real FS/network sandboxing is DEFERRED to P4.3/A1, which **wraps** the existing `run_scoped_command`. Retired together with the ADR-031 D1a residual on one path; the env-scoping does not reverse. |
| Hardcoded `pytest` / `ruff` runner | **Low** — additive; a config-driven runner can replace the fixed argv0 without changing the posture. |

---

## References

- ADR-028 D2 (trust binary), D3 (subprocess deferral, "c2 env-leak class"), D5 (single-writer liveness bound), D6 (empty-executor-diff) — **D3 amended by this ADR**.
- ADR-031 D1a (`RB-FS/NET` honest residual), D2 (subprocess-trust seam, one protocol), HR#2 (empty-executor-diff) — **D2 lightly extended by this ADR (annotation)**.
- ADR-033 D5 (in-process B2, no-subprocess carry-forward #6), D6 / R2-N1 (snapshot_excerpt untrusted-framing + `mcp__` exclusion filter).
- ADR-032 (constitution-test-forbids-`verify=False` precedent → applied to `shell=True`).
- P4-roadmap §7 (flagship loop / value-first), §8 (heavy-set dual-lens), §10 (constitutional spine, honest-residual inscription).
- `src/orchestrator/tools/executor.py:158-202` (Posture-B cap path), `mcp/subprocess_trust.py` (seam), `agents/selection.py:92-130` (excerpt exclusion), `api/app.py:454` (`current_event` channel).
