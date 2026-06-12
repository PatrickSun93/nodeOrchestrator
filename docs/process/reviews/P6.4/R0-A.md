---
task_id: P6.4
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 3
  note: 1   # N1 — pre-existing repo-wide ruff-format debt; orthogonal to P6.4, non-gating
---

# R0-A (impl) — P6.4 descriptive doc-pin: inscribe E+F egress residuals into ADR-037 D5

**Reviewer:** architect-partner (Claude Opus 4.8, 1M ctx), independent session.
**Artifact:** `origin/claude/P6.4-impl` @ `3fac69c` (`P6.4-1: inscribe E+F into ADR-037 D5 + correct egress_proxy docstring + pin F fail-closed`) — single atom / single commit. Diff vs `origin/main`: 3 files, +67 / −5.
**Method:** read-only via `git diff origin/main...origin/claude/P6.4-impl` (stayed on `main`, no checkout of the shared tree). Gates run **independently** in an isolated detached worktree (`uv sync --all-extras`).
**Inputs:** brief (`architect-briefs/P6.4.md`, option-2 ratified), senior plan (`senior-plans/P6.4.md`, `plan_has_adr=false`), ADR-037 D2/D4/D5 + Amendment 1 (A1-1/A1-5).
**State at review:** `awaiting_R0_A` (the senior plan-vs-impl + R0-B legs landed during this review; state coherent with reality). This R0-A is mandatory regardless of plan-vs-impl verdict (ADR-008 Amendment 1 — W-005 Route B).

This is a **descriptive doc-pin**: the only question is *does it inscribe exactly what already ships, with zero egress behaviour/mechanism change?* Verified against the three dispatch objectives below — **yes, on all three.**

---

## Objective 1 — Zero egress behaviour / mechanism change — ✅ HELD

- **`egress_proxy.py` is docstring-only.** The single hunk is the module docstring (`:14-16`): `Both transports:` → `Supported transports:`, separating `https` (CONNECT → tunnel) from `plain http` (absolute-form GET → 405 → fail-closed). The **executable body (`:100-219`) is byte-identical** — no hunk touches `_serve`/`_handle`/the allowlist/`_send_response`/`_relay`. The CONNECT-only check + 405 branch at **`egress_proxy.py:140-141`** (`parts[0].upper() != "CONNECT"` → `_send_response(client, b"405 Method Not Allowed")`) is unchanged (read against the live file).
- **`spawn.py` is not in the changeset.** `_create_network` (`spawn.py:226-230`: `network create --driver bridge`, **no `--internal`**) is untouched — **E is inscribed, never changed**. The §5 red line (no behaviour fix to E or F; no D2 touch) held.
- **Spine byte-frozen.** The diff contains zero change to `_execute_local_call`, the autonomy gate, `LLMPurpose`, `run_pipeline`, or the COUNTDOWN spine (the slice adds no call path — only a docstring, a test, and ADR text). **No new `LLMPurpose`** (the changeset introduces no judgment/routing surface).

## Objective 2 — ADR-037 D5 inscription is accurate (A1-5 shape, faithfully verify-cited) — ✅ HELD

- **Two D5 bullets** appended after the `Cross-platform tails` bullet, in the existing **bold-lead-in + one honest sentence** style:
  - **F** cites `egress_proxy.py:140-141` (the CONNECT-only 405 branch — **verified accurate**), frames it as *"Consistent with D4's fail-closed default — a minor functional limitation, not a security hole"* — faithful to D4 (`:68-72`) + the carry-forward "no silent fail-open" (`:35`). `https` correctly carved out as unaffected (CONNECT path). Cross-links its pin test by name.
  - **E** cites `spawn.py:226-230` (**verified accurate** — the no-`--internal` bridge create), frames it as a *bounded* residual: CONNECT proxy (A1-1), not the bridge firewall, is the enforcement; bounded by DNS-disabled (`--dns 0.0.0.0`) + `--cap-drop=ALL` + `nobody` + operator-image; `--internal` withheld because it can break `host.docker.internal`→proxy reachability. Faithful to A1-1 (`:92`) + D2 (`:55`). Neither under- nor over-claims.
- **Amendment 2 note** placed after A1-6 (`:102`), before *Considered alternatives* (`:106`): declares `plan_has_adr=false`, no Accept gate, **same weight as A1-5**; names the two D5 bullets as the canonical inscription and itself as the audit trail; correctly cites the P4.3 dual-lens (PR #58 / `cb57019`) as the source. **Faithful A1-5 mirror** (canonical D5 inscription + dated audit note); descriptive-only, the enforced surface is untouched.

## Objective 3 — F fail-closed regression test is valid (pins 405; future-loosen → FAIL) — ✅ HELD

- `test_f_plain_http_fails_closed_405` sends the exact absolute-form GET in-container `urllib` emits for a plain-`http://` URL (`GET http://allowed.internal/ HTTP/1.1\r\n...`) straight to the `EgressProxy` object and asserts `b"405"`. The request hits `_handle` → method `GET` ≠ `CONNECT` → 405 at **`:140-141`**.
- **Hermetic + correctly bounded.** The 405 is returned *before* the allowlist check (`:159`) and *before* any upstream dial (`:172`), so the test needs no live upstream and no Docker — the proxy-object boundary the module already uses. Constructor signature matches (`hostname`/`pinned_ip`/`pinned_port`); `socket`/`time` already imported.
- **True fail-on-LOOSEN tripwire.** If anyone later teaches the proxy to forward non-CONNECT methods (flip F from fail-closed → fail-open-for-http — the §5-prohibited behaviour change), the 405 assertion **FAILS**. The test docstring states this contract + that such a change needs an ADR-037 D2 amendment + architect dispatch. This is the contributing.md-Q5 analogue for a doc-pin slice (no behaviour to revert → pin against a future loosening).
- **Passes:** `tests/sandbox/test_egress_proxy.py` 8/8 (7 existing + this new F pin).

---

## Independent gate run (isolated worktree, `uv sync --all-extras`)

| Gate | Result |
|---|---|
| `ruff check src tests` | ✅ `All checks passed!` |
| `mypy` (`files = src,tests`, `--strict`) | ✅ `no issues found in 310 source files` |
| `pytest -q` | ✅ all passed (only a pre-existing Starlette deprecation warning) |
| `ruff format --check src tests` | ⚠️ exit 1 — **50 files would be reformatted, but ALL are pre-existing and NONE are touched by P6.4.** P6.4's own two files (`egress_proxy.py`, `tests/sandbox/test_egress_proxy.py`) are **format-canonical** (absent from the would-reformat list). See N1. |

## Findings

### 🟢 G1–G3 — the three objectives above all HELD (zero egress change · honest D5 inscription · valid fail-on-LOOSEN pin).

### 📝 N1 (non-gating, **pre-existing**, orthogonal) — repo-wide `ruff format --check` debt
Running the documented gate (`contributing.md:195` — "`ruff check` and `ruff format` must pass"; no CI, local-only) **repo-wide** reports **50 non-conformant files** (260 already formatted). **Every one is pre-existing** (e.g. `api/app.py`, `pipeline/*`, `plugins/*`, `tools/*`, and ~30 test files) — P6.4 touches none of them, so it cannot have caused them. **P6.4 itself is format-clean** and actually *normalises* one pre-existing line: the lone "out-of-plan" diff line is a ruff-format auto-collapse of an existing multi-line assert in `test_rw8_proxy_refuses_redirect_host` (fits one line under `line-length=100`) — inert gate-hygiene collateral, also noted clean by senior G6 + R0-B.

**Why neither prior lens surfaced it:** senior plan-vs-impl and R0-B both scoped their format check to the *changed* files (R0-B: "2 files already formatted"); this R0-A ran it repo-wide. **This is NOT a P6.4 defect and does NOT gate this slice** — it's a standing divergence between the documented gate ("ruff format must pass") and repo reality. Recommend the architect consider a separate one-shot repo-wide `ruff format` hygiene slice (orchestrator-routable; zero behaviour risk). **Surfaced for awareness, not routed** — not a P6.4 α/β/γ question.

---

## Verdict

**CLEAN.** P6.4 is a faithful, strictly-bounded descriptive doc-pin: E+F inscribed into the ADR-037 D5 ledger (A1-5 weight) with a dated Amendment-2 audit note, the egress_proxy docstring over-claim corrected docstring-only, and F's fail-closed 405 pinned by a fail-on-LOOSEN regression test asserting genuinely-shipped behaviour. **Zero egress semantic / mechanism / code-path change; spine byte-frozen; no new `LLMPurpose`; no D2 touch; no new ADR; no routing question.** Three-way convergent clean (senior plan-vs-impl 7🟢 + R0-B cross-family 1🟢 + this R0-A 3🟢). The single observation (N1) is pre-existing repo-wide format debt, orthogonal to P6.4 and non-gating.
