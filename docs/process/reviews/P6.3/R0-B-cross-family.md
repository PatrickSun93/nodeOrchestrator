---
task_id: P6.3
round: R0-B
review_lens: cross-family (runtime-failure + security; per dual-lens-r0b.md §contrarian)
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 3
impl_commits_reviewed:
  - ffab366 (P6.3-G1: record_preference preserves created_at)
  - 50f9428 (P6.3-H1: stream-to-temp + incremental hash + cap-during-stream)
gates:
  ruff: pass
  mypy: pass (--strict)
  pytest: 40/40 pass (30 entity + 10 fetch, incl new G1/H1 discriminating tests)
---

# P6.3 R0-B cross-family review

## Lens preamble

This review applies the cross-family lens per dual-lens-r0b.md: runtime-failure
modes, security-integrity surfaces (especially H1's plugin-fetch path), and
concurrency edge cases. The primary bias to over-correct: Claude-family reviewers
tend to trust that if the types and happy paths are right, the runtime is right.
This lens instead asks: what happens when the stream breaks mid-byte, the cap
fires at exactly the wrong chunk boundary, or a defensive guard silently changes
the failure mode?

**Scope:** product only (G1 = `memory/entity.py`, H1 = `plugins/fetch.py`). Both
are pure bug-fixes conforming to existing ADRs (ADR-020 D2, ADR-031 D5) — no
contract touch, no spine change, no new LLMPurpose.

**Gates:** ruff clean, mypy --strict clean, 40/40 pytest pass (30 entity + 10
fetch, including the 3 new discriminating tests: `test_upsert_preserves_created_at`,
`test_ft9_oversized_bundle_capped_during_stream_bounded`, `test_ft10_valid_multichunk_streamed_stages`).

---

## Findings

### 🟡 Y1 — G1: `and existing_created_at is not None` guard deviates from plan, creates silent-duplicate fallthrough

**File:** `src/orchestrator/memory/entity.py:146`

**What the plan said (senior-plan §2):**

> When the matching row is found and `existing_id` is set, also capture
> `existing_created_at`. [...] Use the existing condition `if existing_id is
> not None:`.

**What the impl has:**

```python
if existing_id is not None and existing_created_at is not None:
```

The junior added `and existing_created_at is not None` — a guard not present in
the plan. If this guard were ever `False` (i.e., a matching row exists but its
`created_at` is `None`), the code silently falls through to the INSERT path,
creating a **duplicate preference row** instead of upserting the existing one.
This is a silent correctness corruption.

**Why it's yellow, not red:** The `entity` DDL has `created_at INTEGER NOT NULL`
(`store.py:73-80`), so `existing_created_at` can never be `None` in practice.
The guard is dead code today. However, it introduces a latent wrong-failure-mode
path: if the schema invariant were ever violated (DB corruption, migration error),
the code would silently duplicate rows instead of raising a visible error. The
plan's simpler condition `if existing_id is not None:` fails with an unambiguous
`TypeError` if `created_at` is missing — a strictly better failure mode than
silent corruption.

**Suggested investigation:** Remove `and existing_created_at is not None` to
match the plan. If the junior added this for mypy strict-mode safety (since
`row["created_at"]` is `Any`), the type-narrow should happen at the capture point
instead (`assert existing_created_at is not None` or `cast`) — fail loud, not
silent.

---

### 🟢 G1-advisory — Plan conformance otherwise exact

- `existing_created_at = TimestampMs(row["created_at"])` captured at the loop
  match (`entity.py:143`). ✅
- `created_at` dropped from the UPDATE SET clause (`entity.py:150`) — only
  `attributes` and `evidence` are mutated. ✅
- Returned `Entity.created_at` uses `existing_created_at` (`entity.py:159`). ✅
- INSERT branch (new preference) unchanged — `ts` is still the create-time for
  genuinely new rows. ✅
- Docstring updated per DP-2: "created_at is preserved (only value/evidence
  mutate)" (`entity.py:119`). ✅
- Code comment at UPDATE: "created_at is immutable across upserts — only
  value/evidence mutate (ADR-020 D2)" (`entity.py:148`). ✅
- `test_upsert_preserves_created_at` is discriminating: reverting SET …
  `created_at = ts` + return `created_at=ts` would fail both `== 1000` asserts.
  ✅

---

### 🟢 H1-advisory-1 — Digest-before-extract ordering preserved; cap enforcement correct

The core security property (ADR-031 D5: sha256 of the complete compressed bytes
verified BEFORE any extraction) is correctly preserved under streaming:

1. `_stream_to_file` computes sha256 incrementally over each chunk
   (`fetch.py:77: hasher.update(chunk)`) and returns the finalized hex digest
   after the complete stream (`:91: return hasher.hexdigest()`).
2. `fetch_plugin_bundle` verifies `actual_digest == expected_hex` at `:204`
   BEFORE calling `_detect_and_extract` at `:217` — the verify-before-extract
   sequence is byte-identical to the pre-fix ordering.
3. The cap is enforced **during the stream** (`:73: if total > _MAX_BUNDLE_BYTES`),
   immediately raising `FetchError("bundle too large: > ... limit (capped during stream)")`
   — no post-hoc buffer-and-reject. The `>` comparison means exactly
   `_MAX_BUNDLE_BYTES` is accepted (within bounds), `_MAX_BUNDLE_BYTES + 1` is
   rejected. ✅
4. On cap trigger, `FetchError` propagates through `except FetchError: raise`
   (`:197-198`) unwrapped; the partial temp file is cleaned by the existing
   `finally` block (`:246-248`). ✅

Edge cases traced:
- **Connection drop mid-stream:** `iter_bytes()` raises → caught by
  `except Exception` (`:199-200`), wrapped as "download failed". Partial temp
  file cleaned. ✅
- **HTTP error status (404, 500):** `raise_for_status()` at `:69` raises inside
  the `with client.stream(...)` context → context manager exits cleanly →
  caught by `except Exception`. ✅
- **Empty chunks from iter_bytes():** `len(chunk) == 0` → total unchanged, no
  bytes written/hashed. Harmless.
- **Exactly `_MAX_BUNDLE_BYTES`:** `total > cap` is `False` → download
  completes, hash finalized, digest verified, extraction proceeds. Correct.

---

### 🟢 H1-advisory-2 — Impl hygiene: dead code removed, timeout discipline correct

- `_download` function (old `:222-236`) properly deleted — no remaining callers
  (`grep -rn _download src/ tests/` → zero hits post-impl). ✅
- `_compute_sha256` (old `:58-59`) properly deleted — replaced by inline
  `hasher.hexdigest()` in `_stream_to_file`. Zero remaining references. ✅
- Caller-supplied client path respects its own timeout (no override); default
  path sets `_FETCH_TIMEOUT_S = 30.0` with `verify=True` preserved. ✅
- `test_ft9` (bounded-consumption) is the real discriminators: reverts to
  `response.content` → entire N-byte body pulled → `pulled["bytes"] < total_n`
  assert fails. `test_ft10` (multi-chunk valid bundle) proves incremental
  hashing produces the correct final digest. ✅

**Pre-existing issue noted (no finding):** `tempfile.mkstemp` at `:190` returns
an `_fd` that is never closed. This fd leak exists in the pre-fix code and is
unchanged by this diff. Not introduced here; out of scope for this review cycle.

---

### 🟢 H1-advisory-3 — DP-3(a) read-back bounded-safe

After digest verification, `tmp_bundle.read_bytes()` (`:211`) reads the entire
verified temp file back into memory for extraction. The file is at most
`_MAX_BUNDLE_BYTES` (50 MB) — bounded and safe. The OOM vector was the
**unbounded** `response.content` download; the bounded read-back is explicitly
the mechanism the plan chose (DP-3 mechanism (a)). The existing extractors
(`_extract_zip`, `_extract_tar`) are unchanged. ✅

---

## Synthesis

Both atoms are correct in their core invariants. G1 properly preserves
`created_at` across upserts; H1 properly streams with cap-during-download and
preserves the digest-before-extract ordering. Gates are green; discriminating
tests are in place.

The one deviation is Y1 — a defensive guard that, while harmless today (NOT NULL
schema), creates a wrong failure mode (silent duplicate instead of loud error)
compared to the plan's design. Architect should route whether to fix or accept.

No 🔴 findings. The streaming implementation is structurally sound across the
failure modes examined (connection drop, HTTP errors, cap-at-chunk-boundary,
empty chunks). The cross-family lens does not find runtime-integration gaps
comparable to P1.4's `event_store.append` failure-path or P2.4's
all-agents-fail caller-contract findings.
