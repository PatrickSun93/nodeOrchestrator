# LLM Response Recordings

This directory holds recorded provider responses for VCR-style
integration tests. A test that needs a real LLM call captures the
response on first run; subsequent runs replay from the recording so
tests stay fast and deterministic.

**Format and tooling come in P1.1 commit 2.** This README is the
placeholder during interface freeze.

## Why both `MockProvider` and recordings?

`MockProvider` is for unit tests where the test author writes the
canned reply explicitly — `(AGENT_RESPONSE, "agent:prober") -> "what
do you mean by X?"` — to assert downstream behavior given that reply.

Recordings are for *prompt drift* tests: "does this prompt actually
make Claude respond in the expected shape?" The test asserts on the
*real* response. When the prompt changes, the response changes, and
the recording is invalidated — forcing the contributor to re-record
and re-assert. This catches the canonical failure mode where someone
edits a system prompt and the agent's output silently shifts.

## Workflow (preview, P1.1 commit 2)

1. Mark the test:
   ```python
   @pytest.mark.llm_recording("prober_first_question")
   def test_prober_asks_clarifying_question(...):
       ...
   ```
2. **First run**, with `RECORD_LLM=1` env var: real provider invoked;
   response saved to `recordings/prober_first_question.json` (request
   hash + response envelope).
3. **Subsequent runs**: replay from the file. If the request hash
   doesn't match (prompt changed), test fails with "recording stale".
4. To re-record: delete the file (or set `RECORD_LLM=1` again) and
   re-run. Diff the new recording against the old in PR review.

## What is committed

- The `.json` recording files for prompts/agents that have stable
  expected behavior. Treat these as *fixtures*, not as truth — they
  capture a particular moment in time and are re-recorded when the
  underlying prompt is intentionally changed.
- This README.

## What is NOT committed

- Recordings produced by `RERECORD_LLM=1` runs (they go to a separate
  `_pending/` dir and require explicit rename + diff).
- API responses containing secrets (the recording format strips auth
  headers; the recorder validates this before writing).
