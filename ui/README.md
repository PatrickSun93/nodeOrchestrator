# Orchestrator UI

React/TS frontend for the Orchestrator — reads a room via HTTP + WebSocket and sends user intent.

## Node setup

```bash
# 1. Use the pinned node version (requires nvm)
nvm use        # reads .nvmrc (node 24)

# 2. Install dependencies
npm install

# 3. Start dev server (proxy → http://127.0.0.1:8000)
npm run dev
```

## Gate (run before every PR)

```bash
npm run gate
```

Runs: `eslint` + `prettier --check` + `tsc --noEmit` + `vitest` + **codegen-freshness** check.

The codegen-freshness step re-generates `src/api/schema.ts` from `../src/orchestrator/api/openapi.json`
and fails if the committed file is stale. Re-run `npm run codegen` and commit the updated file when
the contract changes.

## Scripts

| Script | What |
|---|---|
| `npm run dev` | Start Vite dev server on :5173 (proxies `/rooms` + `/events` to :8000) |
| `npm run build` | TypeScript compile + Vite production build |
| `npm run gate` | Full frontend gate (lint + format + typecheck + test + codegen:check) |
| `npm run codegen` | Re-generate `src/api/schema.ts` from the OpenAPI contract |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run test` | Vitest |
