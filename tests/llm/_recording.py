"""LLM call recording — VCR-style replay infrastructure.

A recording is a captured (LLMRequest, LLMResponse) pair stored as
JSON under ``tests/llm/recordings/<name>.json``. Tests that exercise
prompt-shape end-to-end load a recording and replay it; the request
hash detects prompt drift (when the prompt changes the hash changes,
the recording becomes stale, and the test forces a re-record).

This module provides:

- ``Recording`` — Pydantic model for the file format.
- ``load_recording(name)`` — read a JSON file from
  ``tests/llm/recordings/``.
- ``save_recording(name, recording)`` — write a JSON file.
- ``hash_request(request)`` — deterministic hash for drift detection.

P1.1 commit 2 scope is the *infrastructure*. Full pytest plugin with
``@pytest.mark.llm_recording`` and ``RECORD_LLM=1`` env-var capture
mode comes when we have live LLMs to record (P1.2+). The
``readme.md`` in ``recordings/`` describes the planned workflow.

The format is also useful as-is: tests can hand-author canned
recordings to drive ``MockProvider`` with realistic shapes without
booting any pytest plugin.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from orchestrator.llm.types import LLMRequest, LLMResponse

RECORDINGS_DIR = Path(__file__).parent / "recordings"


class Recording(BaseModel):
    """One LLM call captured for replay.

    ``request_hash`` is computed over the canonical JSON of ``request``.
    When a test's prompt changes (system prompt, message list, tools,
    temperature, etc.), the hash changes and the recorded response is
    flagged stale rather than silently used against a different prompt.
    """

    name: str
    request_hash: str
    request: LLMRequest
    response: LLMResponse

    model_config = ConfigDict(frozen=True, extra="forbid")


def hash_request(request: LLMRequest) -> str:
    """SHA-256 of the request's canonical JSON, prefixed ``sha256:``.

    The fields excluded from the hash are the ones whose change does
    NOT meaningfully change the prompt:

    - ``request_id`` — random per call, not part of the prompt shape.

    Inclusion / exclusion of fields is intentional. If a field's
    change should invalidate the recording, include it. ``temperature``
    is included because a different temperature is a different test
    intent. ``caller_agent_id`` is included because changing the agent
    is a different recording. ``extra_params`` is included.
    """
    payload = request.model_dump(mode="json", exclude={"request_id"})
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def load_recording(name: str, base_dir: Path | None = None) -> Recording:
    """Load ``tests/llm/recordings/<name>.json`` into a Recording.

    Raises:
        FileNotFoundError: no such recording.
        pydantic.ValidationError: file is malformed or out of date with
            the current Recording schema.
    """
    base = base_dir or RECORDINGS_DIR
    path = base / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Recording.model_validate(raw)


def save_recording(name: str, recording: Recording, base_dir: Path | None = None) -> Path:
    """Write a recording to ``tests/llm/recordings/<name>.json``.

    Creates the directory if missing. Returns the written path so
    tests can assert on it.
    """
    base = base_dir or RECORDINGS_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{name}.json"
    payload = recording.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
