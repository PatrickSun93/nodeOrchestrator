---
task: P4.7-FE
review: R0-A (single-lens sanity)
reviewer: architect-partner
date: 2026-06-07
dual_lens: false          # single-lens sanity per architect dispatch (low-risk frontend, no new ADR)
scope: ui/ only — zero src/orchestrator product code
verdict: clean            # round-2 (round-1 was needs_architect; F1 routed α-lite by architect, now resolved)
verdict_history:
  - round: 1
    commit: 178cfe0
    verdict: needs_architect
    note: spine clean (C1/C2/C3/C5); F1 prettier gate-red needed a block-vs-nit routing call
  - round: 2
    commit: 10bfe26        # P4.7-FE-fix
    verdict: clean
    note: >
      F1 routed α-lite by architect — resolved. 4 P4.7-FE-new files now pass prettier;
      8 pre-existing prettier debt deferred to hygiene task #95; N2 (err.reason) + N4
      (*.tsbuildinfo gitignore) fixed; N1 (probeAuth catch-all) + N3 (hand-typed contract
      not codegen-locked) left noting. Fix is formatting + 2 nits only — eslint + vitest
      constitutional tests re-green ⇒ no view+intent/auth regression.
findings_count: 0         # round-2: F1 resolved, N2/N4 fixed; N1/N3 remain as noted nits (non-blocking)
findings: { red: 0, yellow: 0, nits: 2 }   # round-1 was 0R/1Y/4nit
gates:
  lint:          pass      # eslint src — incl. no-fetch/WebSocket-outside-api rule (ADR-026 D4 HR#2); re-green round-2
  format_check:  deferred  # round-2: 4 P4.7-FE-new now PASS; 8 pre-existing → hygiene task #95 (architect α-lite)
  typecheck:     pass      # tsc --noEmit, exit 0 (both rounds)
  test:          pass      # vitest — 10 files / 107 tests, incl. constitutional no-fetch test (both rounds)
  codegen_check: pass      # schema.ts fresh vs openapi.json
  build:         pass      # tsc -b && vite build, exit 0 (round-2: 1m7s)
constitutional_checks:
  view_intent_decides_nothing: pass   # C1
  auth_not_bypassed:           pass   # C2
  contract_bound_correctly:    pass   # C3
  gates_green:                 pass   # C4 — round-2: architect-named (build/tsc/eslint) green; 4-new prettier resolved; 8 pre-existing deferred #95
  no_product_code_touched:     pass   # C5
---

# P4.7-FE R0-A — single-lens sanity

Reviewing commit `178cfe0` ("three surfaces — auth login, E2 plugin management, E3 config read-only")
on branch `claude/P4.7-FE-impl`. Light frontend track: single-lens R0-A sanity, no dual-lens, no new
ADR (architect dispatch). Constitutional spine = ADR-026 §D4 (annotated P4.5 → ADR-039 for the GUI
credential path), contract = ADR-038 D5 (plugins) + ADR-039 D3 (login).

This is a **sanity pass, not a deep code review**. Block triggers were limited to: view+intent
violation / auth bypass / contract error / gate red. Pure style/UX → nit.

## Scope confirmation (C5 — PASS)

`git diff --name-status 5b2c34b..178cfe0` touches **only** `ui/**` + `.workflow/P4.7-FE.yaml`.
Zero `src/orchestrator/` product code. ✓

## C1 — view+intent only / decides-nothing (PASS)

Mechanically proven, not just read:
- **eslint** (`no-restricted-globals`/`no-restricted-imports` per ADR-026 D4 HR#2) — green.
- **vitest constitutional test** (asserts no direct `fetch`/`WebSocket` outside `ui/src/api/`) —
  green (part of the 107 passing tests).
- Manual confirmation: every network call funnels through the single typed `request<T>` wrapper in
  `ui/src/api/client.ts`. Components import named functions (`getPlugins`, `enablePlugin`, `login`, …)
  — no scattered `fetch`.
- `ConfigPage.tsx` is pure static display (read-only, no API at all) — decides nothing by construction.
- `App.tsx` auth gating (`authStatus === "unauthenticated" → <LoginPage/>`) is a **view** gate, not a
  security gate; the backend still 401s any protected call regardless of what React renders.
- Plugin actions are shown to **all** authenticated users with **no** client-side role pre-judgment —
  this is the *correct* decides-nothing posture (backend enforces; see `app.py:1190` "authenticated ⇒
  allowed; role check (DP3b) would gate here").

## C2 — auth not bypassed (PASS)

Matches the ADR-026 D4 HR#1 P4.5→ADR-039 annotation verbatim ("carries a credential … but still
decides nothing"):
- Login carries an **HttpOnly** cookie (`app.py:788` `set_cookie(... httponly=True, secure=True,
  samesite="strict")`). Frontend cannot read or forge it; `BASE = ""` (same-origin) → fetch's default
  `same-origin` credentials mode carries the cookie automatically.
- `authStore.ts:18-24` stores `userId` in `localStorage` strictly for **display** after refresh,
  with an explicit comment "display-only — auth is always verified server-side." No principal forging.
- `probeAuth()` (`client.ts:164`) and the global 401 handler (`client.ts:53-65`, wired in `App.tsx:38`)
  **react** to backend enforcement — they never make an authz decision.
- Backend reads principal from `request.state.principal` (server-derived, never body — ADR-039 D7),
  and `_LoginRequest`/`_AdmitRequest` carry `extra="forbid"` forge guards (`app.py:172,236`).

## C3 — contract bound correctly (PASS)

Plugin management binds the P4.7-BE endpoints exactly. Shape-match against the BE response models:

| FE type (`client.ts`) | BE model (`app.py`) | match |
|---|---|---|
| `PluginInfo {plugin_id, enabled, version, provenance, provenance_kind, fetched}` | `_PluginInfo` (constructed `app.py:1175-1182`) | ✓ |
| `AdmitRequest {source_url, digest, version?}` | `_AdmitRequest` (`app.py:233`, used `app.py:1274-1276`) | ✓ |
| `PluginWriteResponse {effect:"next_restart"}` | `_PluginWriteResponse` (`app.py:246`) | ✓ |
| `LoginResponse {user_id}` | `JSONResponse({"user_id": …})` (`app.py:786`) | ✓ |

Endpoints called: `GET /plugins`, `POST /plugins/{id}/{enable,disable,admit}`, `DELETE /plugins/{id}`,
`POST /login`, `POST /logout` — all present in `app.py` and all proxied in `vite.config.ts`.

**Boot-only write semantics surfaced correctly** (the key E2 requirement): after every write
(`PluginsPage.tsx:54,80`) a restart banner is shown — "⚠️ 操作已记录，将在下次重启后生效" — and the
response type encodes `effect: "next_restart"`. This is the `effect:next_restart` contract made visible
to the user. ✓

Login binds ADR-039 D3 (`LoginPage.tsx:20` → `POST /login {user_id, password}` → `{user_id}` + cookie). ✓

## C4 — frontend gates (MIXED → finding F1)

Architect-named gates **all green**: eslint ✓, `tsc --noEmit` ✓ (exit 0), `npm run build` ✓ (exit 0).
Also green: vitest (107 tests), codegen:check (schema.ts fresh).

The **full** `npm run gate` (which ADR-026 D4 defines to include `prettier --check`) is **red** at
format:check only → **F1** below.

---

## 🟡 F1 — `prettier --check` red (gate-red, but mostly pre-existing + pure-formatting)

`npm run gate` fails at `format:check`. 12 files flagged, which split cleanly:

- **8 PRE-EXISTING** (NOT in the P4.7-FE diff → already red at base `5b2c34b`):
  `App.module.css`, `Composer.module.css`, `ConnectionStatus.module.css`, `MessageItem.module.css`,
  `PendingDecision.module.css`, `RoomCreate.module.css`, `RoomPicker.module.css`, `index.css`.
- **4 P4.7-FE-INTRODUCED** (junior did not `prettier --write` before push):
  `api/client.ts`, `App.tsx`, `components/NavBar.module.css`, `components/PluginsPage.tsx`.
  (The other new files — `authStore.ts`, `ConfigPage.*`, `LoginPage.*`, `NavBar.tsx`,
  `PluginsPage.module.css` — pass prettier; formatting was applied inconsistently.)

**Why this is a routing call, not a clean pass or an obvious block.** The dispatch contains two
criteria that point opposite ways here:
- "gate 红才拦" → `format:check` *is* part of the ADR-026-defined gate, and it *is* red.
- "纯样式/UX 小问题记 nit 不拦" → prettier is *pure formatting* (zero logic/behavior change), which
  reads as nit-not-block.

The P4.7-FE portion is mechanically trivial (`prettier --write` on 4 files); the larger 8-file red is
pre-existing debt this slice neither caused nor is scoped to fix.

**My lean (architect-partner surfaces, does not decide):** α-lite — have junior `prettier --write` the
**4 new** files so this slice leaves the gate no worse, and split the **8 pre-existing** files into a
separate `ui/` format-hygiene cleanup task (they predate P4.7-FE and live outside its scope). Not
constitutionally blocking — the spine (C1/C2/C3/C5) is fully intact.

**→ architect: is prettier-red a blocking gate-red or a non-blocking style nit? And for the split —
fix-the-4-now / defer-the-8 / accept-as-is?**

---

## Nits (non-blocking — record only)

- **N1** `probeAuth()` catch-all returns `true` (`client.ts:170`): any non-`AuthError` (network error /
  500) is treated as "authenticated", letting the user into the authed shell before the first real call
  fails. Robustness only — **not** a security issue (every protected call is still enforced server-side).
- **N2** `PluginsPage` error display uses `String(err)` (`PluginsPage.tsx:61,92`): the thrown value is an
  `{stage, reason}` object (from `client.ts:68-71`), so the user sees "操作失败：[object Object]".
  Surface `err.reason` instead.
- **N3** Plugin + auth contract types are **hand-typed** in `client.ts:17-40` (comment: "not in
  openapi.json"), so `codegen:check` does not cover them — future BE contract drift on these endpoints
  would pass the gate silently. Consider adding the plugin/auth schemas to `openapi.json` so codegen
  locks them like the room/event types. (Root cause is P4.7-BE not regenerating `openapi.json`; out of
  FE scope to fix here.)
- **N4** `ui/.gitignore` lacks `*.tsbuildinfo` — `ui/tsconfig.tsbuildinfo` (from `tsc -b`) shows as
  untracked. One-line hygiene fix.

## Process note (not a finding — surface to architect)

`.workflow/P4.7-FE.yaml` is still `state: awaiting_brief` though impl is pushed and there is no brief
file. This is consistent with the architect-confirmed **light frontend track** (state machine driven
manually, not formally advanced) — surfaced per the state-machine self-check, **not auto-fixed** (state
files are never hand-edited). Architect may want to `override` it to a terminal state when this slice
lands, or leave the light track informal.

## Verdict (round 1)

**needs_architect** — constitutional spine clean (C1/C2/C3/C5 PASS; the no-fetch + auth-no-forge
invariants are mechanically proven by the passing eslint + vitest constitutional tests). The single
open item is **F1** (prettier gate-red), which sits exactly on the seam between the dispatch's two
criteria and needs a one-line routing call. 4 nits recorded, none blocking.

---

# Round 2 — re-confirm (F1 routed α-lite)

Architect routed F1 as **α-lite**. Junior pushed `10bfe26` ("P4.7-FE-fix: prettier 4 new files +
N4 gitignore + N2 err.reason"). Lightweight re-confirm against `git show 10bfe26`.

**Diff scope** — touches exactly the 4 P4.7-FE-new files + `.gitignore`, nothing else:
`ui/.gitignore`, `ui/src/App.tsx`, `ui/src/api/client.ts`, `ui/src/components/NavBar.module.css`,
`ui/src/components/PluginsPage.tsx`. **Did not touch** any of the 8 pre-existing prettier-debt files;
**did not touch** `src/orchestrator/` (no product code). ✓

**Re-confirm checklist:**

1. **4 new files now pass `prettier --check`** ✓ — `prettier --check src` now flags **only** the 8
   pre-existing files (App.module.css, Composer/ConnectionStatus/MessageItem/PendingDecision/
   RoomCreate/RoomPicker `.module.css`, index.css); none of client.ts/App.tsx/NavBar.module.css/
   PluginsPage.tsx. The 8 remaining are the **deferred** debt → hygiene task **#95** (expected red).
2. **No pre-existing files / no backend touched** ✓ (diff scope above).
3. **Architect-named gates re-green** ✓ — eslint exit 0, `tsc --noEmit` exit 0, build exit 0 (1m7s).
   vitest 107/107 (incl. the constitutional no-fetch test) → **no view+intent/auth regression**.
4. **N2 fixed correctly** ✓ — `PluginsPage.tsx:61,92`: `String(err)` → `(err as {reason?:string})
   .reason ?? "请稍后重试"`, so the human reason surfaces instead of `[object Object]` (both the
   action and admit error paths).
5. **N4 fixed correctly** ✓ — `ui/.gitignore` gains `*.tsbuildinfo`.

**No regression to the spine.** The fix is formatting + N2 (error-display string) + N4 (gitignore)
only. client.ts's reformat is byte-equivalent in behavior (same endpoints/methods/bodies); App.tsx is
a JSX rewrap; NavBar.module.css is a `transition` shorthand split. C1/C2/C3/C5 unchanged and the
mechanical guards (eslint no-fetch rule + vitest constitutional test) are re-green.

**Remaining nits (noting, non-blocking):** N1 (`probeAuth` catch-all returns `true`) and N3
(hand-typed plugin/auth contract not codegen-locked) — left as-is per architect routing.

## Verdict (round 2 — final)

**clean** — F1 resolved (α-lite: 4 new files formatted; 8 pre-existing deferred to #95). N2 + N4 fixed.
N1 + N3 remain as noted nits. Constitutional spine intact and mechanically re-verified. No further
architect-partner action; this is the final R0-A verdict for P4.7-FE.
