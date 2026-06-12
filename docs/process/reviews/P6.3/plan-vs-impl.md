---
task_id: P6.3
kind: plan-vs-impl
reviewer: senior
state_at_write: awaiting_senior_plan_vs_impl
cycle: 1
impl_ref: origin/claude/P6.3-impl @ 50f9428
plan_ref: docs/process/senior-plans/P6.3.md (no ADR; G1 + H1)
verdict: clean
---

# P6.3 plan-vs-impl — verdict: **clean**

Reviewed `origin/main...origin/claude/P6.3-impl` (two commits: `ffab366` G1, `50f9428` H1)
against `docs/process/senior-plans/P6.3.md`. Both atoms are faithful to the plan's Change
sections, each ships its discriminating fail-on-revert test, and there is **no plan-external
expansion**. Gates green (ruff / mypy --strict / pytest). No spine touch, no new `LLMPurpose`,
no ADR amendment, no schema migration — exactly as the plan scoped.

## Scope containment

Exactly the four files the plan names — no drift:

```
src/orchestrator/memory/entity.py
src/orchestrator/plugins/fetch.py
tests/memory/test_entity.py
tests/plugins/test_fetch.py
```

No `.workflow/` or `docs/` changes on the impl branch (no stray junior self-advance commit;
no opportunistic edits). Two independent atoms, two commits — the plan's decomposition exactly.

## Atom G1 — preserve `created_at` (`memory/entity.py`) — faithful

| Plan §2 Change | Impl @ `ffab366` | OK |
|---|---|---|
| Capture `existing_created_at = TimestampMs(row["created_at"])` at the loop match | `entity.py:143` inside the scan-loop `break` branch | ✓ |
| Drop `created_at` from UPDATE … SET (G-lean, not the rejected G-alt) | `UPDATE entity SET attributes = ?, evidence = ? WHERE id = ?` | ✓ |
| Return the preserved create-time | `created_at=existing_created_at` (was `=ts`) | ✓ |
| INSERT branch + `ts = now_ms()` unchanged | untouched | ✓ |
| Mandatory inscription: code comment + docstring touch | comment `# created_at is immutable across upserts … (ADR-020 D2)`; docstring now reads "… in place; created_at is preserved (only value/evidence mutate)" | ✓ |
| Fail-on-revert `test_upsert_preserves_created_at` | added at `test_entity.py:242`; asserts persisted `created_at == 1000` **and** `e2.created_at == 1000` (the two discriminating asserts) | ✓ |

**Defensible micro-deviation (not blocking):** the update guard is written as
`if existing_id is not None and existing_created_at is not None:` (plan showed only the
`existing_id` guard). This is a mypy type-narrowing of `existing_created_at: TimestampMs | None`
so it can be passed as `created_at=`; the two are always set together at the same `break`, so it
is logically identical to the plan's single-guard form — no behavioral expansion. Correct, minimal.

## Atom H1 — stream-to-temp + incremental hash + cap-during-stream (`plugins/fetch.py`) — faithful (cross-family lens)

| Plan §3 Change | Impl @ `50f9428` | OK |
|---|---|---|
| New `_stream_to_file(source_url, http_client, dest_path) -> str` | added; hasher + running `total`, `_consume` does `raise_for_status()` then `iter_bytes()` loop | ✓ |
| Cap enforced **during** the stream | `if total > _MAX_BUNDLE_BYTES: raise FetchError("… capped during stream")` inside the chunk loop | ✓ |
| sha256 computed **incrementally** over the complete bytes | `hasher.update(chunk)` per chunk; returns `hasher.hexdigest()` | ✓ |
| Caller-supplied client keeps its own timeout; only default path sets `_FETCH_TIMEOUT_S = 30.0`, `verify=True` | exactly so | ✓ |
| Rewire: `actual_digest = _stream_to_file(...)`; `except FetchError: raise` before generic wrap | present — "too large"/status errors propagate verbatim | ✓ |
| Delete post-hoc cap check + explicit `tmp_bundle.write_bytes(...)` | both removed | ✓ |
| Verify digest **before** extraction (ADR-031 D5 ordering) | `_parse_digest` → mismatch raise → **then** `bundle_bytes = tmp_bundle.read_bytes()` → extract; `# Step 3` comment retained | ✓ |
| DP-3(a) read-back of the now-verified, ≤cap temp file | `bundle_bytes = tmp_bundle.read_bytes()` after verify | ✓ |
| `_download` removed; `_compute_sha256` removed if no other caller | both removed; `git grep` confirms **zero** remaining callers in `src`/`tests` | ✓ |
| Cleanup (`finally` unlink of tmp_bundle/tmp_staging) unchanged; fetched_plugins_dir untouched on failure | unchanged | ✓ |
| Fail-on-revert `test_ft9_…_bounded` (counting-generator MockTransport, bounded-consumption) | added at `test_fetch.py:296`; asserts `pulled["bytes"] <= cap + chunk` and `< total_n`, and `not (fetched_dir/"huge").exists()` | ✓ |
| Positive `test_ft10_valid_multichunk_streamed_stages` (incremental hash == full-bytes hash) | added at `test_fetch.py:347`; 16-byte chunks, asserts stage + `plugin.yaml` present | ✓ |

ADR-031 D5 (digest-of-complete-compressed-bytes, verified-before-extract) is **preserved** — the
streamed bytes and the verify→extract sequence are byte-identical to the prior path; only the
*where* of the size check moved (post-hoc → during-stream, strictly stronger). ADR-038's
admission-proof path (`app.py:1777`) is untouched (fetch mechanism, which ADR-038 §Scope explicitly
excludes). The "too large" `FetchError` propagates unwrapped (the `except FetchError: raise`
shield), so ft6 + ft9 `match="too large"` both hold.

## Gates (run at impl head `50f9428` in a clean `uv sync --all-extras` worktree)

- **ruff** — `All checks passed!` (4 changed files)
- **mypy --strict** — `Success: no issues found in 2 source files` (`entity.py`, `fetch.py`)
- **pytest** — `tests/plugins/test_fetch.py` + `tests/memory/test_entity.py`: **40 passed**, incl.
  the three new tests collected and green by node id.

## Fail-on-revert verification (executed, not just read)

Spot-checked the cross-family discriminator: reverted `_stream_to_file._consume` to a buffer-all
(`response.read()` then cap) in the throwaway worktree and re-ran ft9 → it **failed** as designed:
`assert 73400320 <= 52428800 + 1048576` (i.e. `pulled["bytes"] == total_n` — the full body was
pulled). This confirms ft9 is genuinely discriminating for the OOM/streaming fix, not merely
re-asserting the cap (ft6's role). G1's test asserts both the persisted-row and returned-Entity
`created_at`, the pair the plan identifies as the discriminating revert-catchers.

## Notes (non-blocking)

- The plan's **recommended-but-optional** ADR-020 D2 clarification note ("rides along, no Accept
  gate") was not inscribed; only the mandatory docstring + code-comment were. The plan made the
  ADR note explicitly optional, so its absence is conformant, not a miss. No ADR amendment was
  required by this slice and none was made — correct.

## Verdict

**clean** — both atoms faithful to the plan, discriminating fail-on-revert tests present and
verified, no scope expansion, gates green, ADR-020 D2 / ADR-031 D5 contracts preserved, spine and
`LLMPurpose` surfaces untouched. No architect decision required.
