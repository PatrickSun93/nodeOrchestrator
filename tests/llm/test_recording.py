"""Tests for the LLM recording infrastructure."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ModelId,
    ProviderId,
    Usage,
    generate_request_id,
)
from tests.llm._recording import (
    RECORDINGS_DIR,
    Recording,
    hash_request,
    load_recording,
    save_recording,
)


def _request(content: str = "hi") -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content=content)],
    )


def _response(req: LLMRequest, content: str = "hello") -> LLMResponse:
    return LLMResponse(
        request_id=req.request_id,
        content=content,
        tool_calls=[],
        model_id_requested=ModelId("m"),
        model_id_used=ModelId("m"),
        provider_id_used=ProviderId("p"),
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=100,
        finish_reason="stop",
    )


class TestHashRequest:
    def test_hash_is_deterministic(self) -> None:
        req = _request()
        h1 = hash_request(req)
        h2 = hash_request(req)
        assert h1 == h2
        assert h1.startswith("sha256:")
        assert len(h1) == len("sha256:") + 64

    def test_hash_excludes_request_id(self) -> None:
        """Two requests differing only in request_id should hash the same."""
        r1 = _request()
        r2 = _request()
        # Different request_ids by construction
        assert r1.request_id != r2.request_id
        # But same content -> same hash
        assert hash_request(r1) == hash_request(r2)

    def test_hash_includes_temperature(self) -> None:
        r1 = LLMRequest(
            request_id=generate_request_id(),
            purpose=LLMPurpose.AGENT_RESPONSE,
            messages=[Message(role="user", content="hi")],
            temperature=0.3,
        )
        r2 = r1.model_copy(update={"temperature": 0.7})
        assert hash_request(r1) != hash_request(r2)

    def test_hash_includes_caller_agent_id(self) -> None:
        r1 = LLMRequest(
            request_id=generate_request_id(),
            purpose=LLMPurpose.AGENT_RESPONSE,
            messages=[Message(role="user", content="hi")],
            caller_agent_id="agent:prober",
        )
        r2 = r1.model_copy(update={"caller_agent_id": "agent:skeptic"})
        assert hash_request(r1) != hash_request(r2)

    def test_hash_includes_messages(self) -> None:
        r1 = _request("A")
        r2 = _request("B")
        assert hash_request(r1) != hash_request(r2)


class TestRecordingRoundTrip:
    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        req = _request()
        resp = _response(req)
        recording = Recording(
            name="test_rt",
            request_hash=hash_request(req),
            request=req,
            response=resp,
        )

        save_recording("test_rt", recording, base_dir=tmp_path)
        loaded = load_recording("test_rt", base_dir=tmp_path)

        assert loaded == recording

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_recording("nonexistent", base_dir=tmp_path)

    def test_load_malformed_raises_validation(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text('{"name": "broken"}')  # missing other required fields
        with pytest.raises(ValidationError):
            load_recording("broken", base_dir=tmp_path)


class TestRecordingFrozen:
    def test_recording_is_immutable(self) -> None:
        req = _request()
        rec = Recording(
            name="x",
            request_hash="sha256:abc",
            request=req,
            response=_response(req),
        )
        with pytest.raises(ValidationError):
            rec.name = "tampered"


class TestSampleRecording:
    """Validates the sample recording shipped in tests/llm/recordings/
    parses against the current Recording schema. This catches
    schema drift — if Recording changes, the sample fails to load."""

    def test_sample_loads(self) -> None:
        rec = load_recording("sample_prober_clarifying_question")
        assert rec.name == "sample_prober_clarifying_question"
        assert rec.request.purpose == LLMPurpose.AGENT_RESPONSE
        assert rec.request.caller_agent_id == "agent:prober"
        assert "clarifying" in rec.response.content or "constraint" in rec.response.content

    def test_recordings_dir_exists(self) -> None:
        assert RECORDINGS_DIR.is_dir()


class TestRecordingHashConsistency:
    """For every recording file shipped in tests/llm/recordings/, the
    stored ``request_hash`` must equal ``hash_request(request)``.
    Catches future re-records where the request changed but the
    hash wasn't recomputed (would silently let a stale recording
    answer for a different prompt). Project-wide invariant for any
    new recording added.
    """

    def test_all_recordings_have_correct_hash(self) -> None:
        recording_paths = sorted(RECORDINGS_DIR.glob("*.json"))
        assert recording_paths, "expected at least one recording in tests/llm/recordings/"
        violations: list[str] = []
        for path in recording_paths:
            recording = load_recording(path.stem)
            expected = hash_request(recording.request)
            if recording.request_hash != expected:
                violations.append(
                    f"{path.name}: stored {recording.request_hash}, computed {expected}"
                )
        assert not violations, "recording request_hash mismatches:\n" + "\n".join(violations)
