# `sources/` vs `connectors/` — directional distinction

## TL;DR

| Directory | Direction | What it does | ADR |
|-----------|-----------|--------------|-----|
| `src/orchestrator/sources/` | **Input** — read data **into** the pipeline | Web fetch, RSS/Atom parse, sandboxed file read | ADR-041 D4 |
| `src/orchestrator/connectors/` | **Output** — write ground-truth facts **out** of the system | External validation event producers | ADR-019 |

## Why the distinction matters

`connectors/` (ADR-019) produces `EXTERNAL_VALIDATION` events — it is a **ground-truth output surface**, writing structured facts from an external authoritative source into the event store.

`sources/` (ADR-041 D4) is the **opposite direction**: it reads raw data from the outside world (web pages, RSS feeds, local files) and returns it as text for the pipeline's analyze stage to reason over.

Placing pipeline input sources in `connectors/` would be a naming collision that inverts the data-flow direction.  Use `sources/` for anything that **reads data in**; use `connectors/` for anything that **writes validated facts out**.

## Security floors

Both `web` and `rss` sources flow through the **identical SSRF floor** as `web_fetch` (`tools/net_trust.py:build_ssrf_client` / `_resolve_and_validate`): scheme allowlist, IP denylist, resolve-then-pin DNS-rebind defence, bounded redirect chain.  A feed URL is attacker-influenceable when user-supplied, so it is never bypassed.

`file` sources are path-sandboxed via `tools/local.py:_check_path`: traversal and symlink-escape are rejected; reads are bounded.

RSS/Atom XML parsing uses `defusedxml` (`forbid_dtd=True`) to prevent XXE injection and billion-laughs entity expansion.  The protection is position-independent: DOCTYPE declarations are rejected at the parser level regardless of comment or PI padding in the prolog.

## Cross-reference

See also ADR-019 (`docs/decisions/ADR-019-*.md`) — the `connectors/` ground-truth output surface.
