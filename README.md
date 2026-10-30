**English | [中文](README.zh-CN.md)**

# Orchestrator

[![CI](https://github.com/PatrickSun93/nodeOrchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/PatrickSun93/nodeOrchestrator/actions/workflows/ci.yml)

**AI research and decision assistant — honest interlocutor, not obedient executor.**

Orchestrator is a multi-agent conversation platform for independent developers who want to think things through rather than just get answers. The agents push back, ask questions, and surface disagreement — they won't make decisions for you, but they'll sharpen yours.

The assistant rooms are backed by a multi-agent orchestrator, an append-only event stream, an autonomy gate (AUTO / COUNTDOWN / HARD-confirm), a sandboxed plugin system, and multi-user authentication.

---

## Features

- **Multi-agent rooms** — each room runs a configurable set of agents (facilitator, skeptic, investigator, planner, …) that respond to user messages and each other via an event stream
- **Autonomy gate** — every tool call is classified by risk score; low-risk ops fire automatically (AUTO), medium ops start a countdown that you can cancel (COUNTDOWN), high-risk ops require explicit confirmation (HARD)
- **Event-sourced history** — all room activity is an append-only event log; snapshots are derived, never authoritative
- **Sandboxed plugins** — plugins run under a syscall allowlist (seccomp / landlock); the plugin registry and lifecycle endpoints are managed through the GUI or REST API
- **Three-layer LLM config** — providers / models / per-agent config are independent; switch from DeepSeek to a local Ollama without touching agent definitions
- **MCP support** — connect external tools (filesystem, database, remote services) via the Model Context Protocol
- **Multi-user auth** — session-cookie auth, fail-closed (no unauthenticated access), per-thread WAL reader pool
- **GUI** — React + TypeScript (Vite) frontend with chat view, plugin management (E2), and config overview (E3); HTTP client types are generated from the committed OpenAPI contract

---

## Installation

### Requirements

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 24 (frontend only)

### Backend

```bash
# Install Python deps (api + mcp extras are required to run the server)
uv sync --extra api --extra mcp

# Copy and fill in config templates
for f in config/*.example; do cp "$f" "${f%.example}"; done
# Now edit config/llm_providers.yaml and config/llm_models.yaml
# to point at your LLM provider(s). See the comments in each file.
```

Config files that need your credentials / endpoints:

| File | Purpose |
|---|---|
| `config/llm_providers.yaml` | LLM provider connections (DeepSeek, Ollama, Claude Code CLI, …) |
| `config/llm_models.yaml` | Model profiles (provider, capabilities, context window) |
| `config/llm_override.yaml` | Optional global model override for all agents |
| `config/email.yaml` | Optional email tool |
| `config/web_search.yaml` | Optional web search tool |

### Frontend

```bash
cd ui && npm install
```

---

## Running

### 1. Create the first user

Auth is fail-closed — the server won't start a remote bind without at least one user, and there is no unauthenticated signup endpoint. Bootstrap the first account:

```bash
# Interactive (prompts for password):
uv run python -m orchestrator.api.admin create-user <your-username>

# Non-interactive (e.g. in a script):
ORCHESTRATOR_ADMIN_PASSWORD=<password> uv run python -m orchestrator.api.admin create-user <your-username>
```

### 2. Start the backend

```bash
uv run python -m orchestrator.api --config config/ --db data/rooms.db
# Binds to 127.0.0.1:8000 by default.
# Use --host / --port to change. Non-loopback binds require TLS at the proxy layer.
```

### 3. Start the frontend

```bash
cd ui && npm run dev
# Vite dev server on http://localhost:5173
# Proxies /rooms /events /plugins /login /logout → :8000
```

Open `http://localhost:5173`, log in, create a room, start thinking.

---

## Screenshots

### Login

![Login page](docs/images/01-login.png)

### Lobby — create or join a room

![Lobby](docs/images/02-lobby.png)

### Plugin management

![Plugin management](docs/images/03-plugins.png)

### Config overview

![Config overview](docs/images/04-config.png)

---

## Design & dev docs

- [`handoff.md`](handoff.md) — architecture, design principles, ADR index
- [`docs/architecture/`](docs/architecture/) — architecture notes (event model, LLM layer, sources vs connectors, test coverage standard)
- [`docs/decisions/`](docs/decisions/) — ADRs (ADR-001..043)
- [`docs/contributing.md`](docs/contributing.md) — PR template and the local gates (the same commands CI runs)

---

## Re-generating screenshots

```bash
# Prerequisites: backend + frontend running, a "demo" user created
LD_LIBRARY_PATH=/tmp node docs/screenshot.mjs
# (LD_LIBRARY_PATH workaround is only needed on systems missing libasound2)
```
