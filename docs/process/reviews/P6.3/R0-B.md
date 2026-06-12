---
task_id: P6.3
round: R0-B
review_lens: cross-family (runtime-failure + security; per dual-lens-r0b.md §contrarian)
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 4
impl_commits_reviewed:
  - ffab366 (P6.3-G1: record_preference preserves created_at)
  - 50f9428 (P6.3-H1: stream-to-temp + incremental hash + cap-during-stream)
gates:
  ruff: pass
  mypy: pass (--strict)
  pytest: 40/40 pass (30 entity + 10 fetch, incl new discriminating tests)
---

# P6.3 R0-B cross-family review

## Lens preamble

Cross-family lens per dual-lens-r0b.md: runtime-failure modes, security-integrity
surfaces (H1 plugin-fetch path), and concurrency edge cases. Primary bias to
over-correct: Claude-family reviewers trust type-correctness → runtime-correctness;
this lens asks what happens when the stream breaks mid-byte, the cap fires at a
chunk boundary, or temp-file state survives an exception path.

Scope: product only (G1 = `memory/entity.py`, H1 = `plugins/fetch.py`). Both are
pure bug-fixes conforming to existing ADRs (ADR-020 D2, ADR-031 D5) — no contract
touch, no spine change, no new LLMPurpose.

Gates: ruff clean, mypy --strict clean, 40/40 pytest pass.

---

## Findings

### 🟢 G1 — `created_at` preservation correct; INSERT branch unchanged

Verified at `src/orchestrator/memory/entity.py`:

- `existing_created_at = TimestampMs(row["created_at"])` captured at loop match (`:143`).
- `created_at` dropped from UPDATE SET (`:150`) — only `attributes` and `evidence` mutate.
- Returned `Entity.created_at` uses `existing_created_at` (`:159`), not `ts`.
- INSERT branch (new preference, `:162+`) unchanged — `ts` still create-time for new rows.
- Docstring updated: "created_at is preserved (only value/evidence mutate)" (`:119`).
- Code comment at UPDATE: "created_at is immutable across upserts" + ADR-020 D2 cite (`:148`).
- `test_upsert_preserves_created_at` is discriminating: revert SET `created_at = ts` + return `created_at=ts` → both `== 1000` asserts fail.

ADR-020 D2 conformance: the ADR inscribes "updates the row's value in place" —
`created_at` was never meant to mutate. The fix makes code match the inscribed
decision. No `updated_at` column added (schema unchanged). Concurrency posture
unchanged (read-modify-write within caller's transaction).

### 🟢 H1 — Digest-before-extract ordering preserved under streaming

The core security property (ADR-031 D5: sha256 of complete compressed bytes
verified BEFORE any extraction) is correctly preserved:

1. `_stream_to_file` computes sha256 incrementally (`fetch.py:77: hasher.update(chunk)`)
   and returns `hasher.hexdigest()` after the complete stream (`:91`). The streamed
   bytes written to `tmp_bundle` are exactly the bytes hashed — no divergence.
2. `fetch_plugin_bundle` verifies `actual_digest == expected_hex` at `:204`,
   BEFORE `_detect_and_extract` at `:217`. Verify-before-extract sequence
   byte-identical to pre-fix.
3. Cap enforced **during** stream (`:73: if total > _MAX_BUNDLE_BYTES`), raising
   `FetchError` immediately — no post-hoc buffer-and-reject. `>` comparison means
   exactly `_MAX_BUNDLE_BYTES` is accepted, `+1` rejected.
4. On cap trigger, `FetchError` propagates through `except FetchError: raise`
   (`:197-198`) unwrapped; partial temp file cleaned by existing `finally` (`:246-248`).

Edge cases traced and confirmed correct:
- **Connection drop mid-stream:** `iter_bytes()` raises → caught by `except Exception`
  (`:199-200`), wrapped as "download failed". Partial temp file cleaned.
- **HTTP error status:** `raise_for_status()` (`:69`) raises inside `with
  client.stream(...)` → context manager exits cleanly → caught by `except Exception`.
- **Exactly at cap:** `total == _MAX_BUNDLE_BYTES` → `>` is False → download
  completes → hash finalized → digest verified → extraction proceeds.
- **Empty chunks:** `len(chunk) == 0` → total unchanged, no bytes written/hashed. Harmless.

### 🟢 H1 — Cap-during-stream is strictly stronger (bounded consumption)

The pre-fix code buffered the entire response via `response.content` before
checking the cap — a multi-GB body would OOM at the `response.content` call. The
fix streams chunk-by-chunk and aborts the moment `total > _MAX_BUNDLE_BYTES`.
Consumption is provably bounded:

- `test_ft9` uses a `MockTransport` with a counting generator serving `N >> cap`
  bytes. Asserts `FetchError("too large")` is raised AND `pulled["bytes"] <=
  _MAX_BUNDLE_BYTES + chunk` AND `pulled["bytes"] < total_n`. Revert to
  `response.content` → entire N is pulled → bounded asserts fail.
- `test_ft10` proves incremental hashing over multi-chunk response produces the
  same final digest as single-shot `hashlib.sha256(bundle).hexdigest()`.
- `test_ft6` (50 MB+1 → "too large") stays green — necessary but not
  discriminating; ft9 is the real fail-on-revert test.

Temp file cleanup is preserved: on any failure (cap, digest mismatch, extraction
error), `tmp_bundle` unlinked in `except` + `finally`; `fetched_plugins_dir`
never touched by a failed fetch (ft7 parallel holds).

### 🟢 H1 — Impl hygiene and timeout discipline

- `_download` function properly deleted — zero remaining references.
- `_compute_sha256` properly deleted — replaced by inline `hasher.hexdigest()`
  in `_stream_to_file`. Zero remaining references.
- Caller-supplied client path respects its own timeout (no override); default
  path sets `_FETCH_TIMEOUT_S = 30.0` with `verify=True` preserved (ADR-032 D2).
- DP-3(a) read-back: after digest verification, `tmp_bundle.read_bytes()` (`:211`)
  reads the verified ≤50 MB temp file for extraction — bounded and safe. The OOM
  vector was the unbounded `response.content`; the bounded read-back is explicitly
  the plan's chosen mechanism.

**Pre-existing note (no finding):** `tempfile.mkstemp` at `:190` returns an `_fd`
never closed. This fd leak exists in the pre-fix code and is unchanged by this
diff. Not introduced here.

---

## Synthesis

Both atoms are correct in their core invariants. G1 properly preserves
`created_at` across preference upserts — conforms to ADR-020 D2, no schema
change, INSERT branch untouched. H1 properly streams with cap-during-download
and preserves the digest-before-extract ordering — conforms to ADR-031 D5,
strengthens the existing cap from post-hoc to during-stream.

The streaming implementation is structurally sound across all failure modes
examined: connection drop, HTTP errors, cap-at-chunk-boundary, empty chunks.
The cross-family lens finds no runtime-integration gaps comparable to prior
cycles' findings (P1.4 event_store failure-path, P2.4 all-agents-fail contract).

No 🔴, no 🟡. Verdict: clean.
