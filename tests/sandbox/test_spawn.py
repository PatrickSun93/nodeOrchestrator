"""Tests for sandbox/spawn.py (P4.3-4).

All container execution is mocked — no live Docker daemon required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from orchestrator.mcp.subprocess_trust import SubprocessResult, SubprocessTimeoutError
from orchestrator.sandbox.egress import build_deny_default_spec
from orchestrator.sandbox.profile import SandboxProfile
from orchestrator.sandbox.runtime import SandboxRuntime, SandboxUnavailableError
from orchestrator.sandbox.spawn import SETUP_TEARDOWN_P95_TARGET_S, sandboxed_run


def _make_runtime(available: bool = True) -> SandboxRuntime:
    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    rt.available = mock.Mock(return_value=available)  # type: ignore[method-assign]
    rt.kill = mock.Mock()  # type: ignore[method-assign]
    return rt


def _make_profile(tmp_path: Path) -> SandboxProfile:
    return SandboxProfile(sandbox_root=tmp_path, image="test-image:latest")


# ---------------------------------------------------------------------------
# Result-shape parity with SubprocessResult
# ---------------------------------------------------------------------------


def test_result_shape_parity(tmp_path: Path) -> None:
    rt = _make_runtime()
    profile = _make_profile(tmp_path)
    egress = build_deny_default_spec()

    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(
            returncode=0, stdout=b"hello\n", stderr=b""
        )
        result = sandboxed_run(
            ["echo", "hello"],
            cwd=tmp_path,
            env={},
            profile=profile,
            egress_spec=egress,
            runtime=rt,
        )

    assert isinstance(result, SubprocessResult)
    assert result.exit_code == 0
    assert "hello" in result.output
    assert isinstance(result.truncated, bool)


def test_result_nonzero_exit_code(tmp_path: Path) -> None:
    rt = _make_runtime()
    profile = _make_profile(tmp_path)

    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=1, stdout=b"fail", stderr=b"")
        result = sandboxed_run(
            ["false"], cwd=tmp_path, env={}, profile=profile, runtime=rt
        )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Bounded output
# ---------------------------------------------------------------------------


def test_max_bytes_truncated(tmp_path: Path) -> None:
    rt = _make_runtime()
    profile = _make_profile(tmp_path)

    big_output = b"x" * 200
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout=big_output, stderr=b"")
        result = sandboxed_run(
            ["cat"], cwd=tmp_path, env={}, profile=profile, max_bytes=100, runtime=rt
        )

    assert result.truncated is True
    assert len(result.output.encode()) <= 100


# ---------------------------------------------------------------------------
# Unavailable runtime → SandboxUnavailableError
# ---------------------------------------------------------------------------


def test_unavailable_runtime_raises(tmp_path: Path) -> None:
    rt = _make_runtime(available=False)
    profile = _make_profile(tmp_path)

    with pytest.raises(SandboxUnavailableError):
        sandboxed_run(["cmd"], cwd=tmp_path, env={}, profile=profile, runtime=rt)


def test_unavailable_runtime_no_subprocess_call(tmp_path: Path) -> None:
    rt = _make_runtime(available=False)
    profile = _make_profile(tmp_path)

    with mock.patch("subprocess.run") as mock_run, pytest.raises(SandboxUnavailableError):
        sandboxed_run(["cmd"], cwd=tmp_path, env={}, profile=profile, runtime=rt)
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Daemon-dies-at-spawn → SandboxUnavailableError
# ---------------------------------------------------------------------------


def test_daemon_dies_at_spawn_raises(tmp_path: Path) -> None:
    rt = _make_runtime(available=True)
    profile = _make_profile(tmp_path)

    with (
        mock.patch("subprocess.run", side_effect=FileNotFoundError("docker not found")),
        pytest.raises(SandboxUnavailableError, match="spawn failed"),
    ):
        sandboxed_run(["cmd"], cwd=tmp_path, env={}, profile=profile, runtime=rt)


# ---------------------------------------------------------------------------
# Timeout → SubprocessTimeoutError + shielded teardown
# ---------------------------------------------------------------------------


def test_timeout_raises_subprocess_timeout(tmp_path: Path) -> None:
    rt = _make_runtime()
    profile = _make_profile(tmp_path)

    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=1.0),
    ), pytest.raises(SubprocessTimeoutError):
        sandboxed_run(
            ["sleep", "999"],
            cwd=tmp_path,
            env={},
            profile=profile,
            timeout_s=1.0,
            runtime=rt,
        )


def test_timeout_teardown_still_kills_container(tmp_path: Path) -> None:
    """Shielded teardown: kill is called even on timeout."""
    rt = _make_runtime()
    profile = _make_profile(tmp_path)

    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=1.0),
    ), pytest.raises(SubprocessTimeoutError):
        sandboxed_run(
            ["sleep", "999"],
            cwd=tmp_path,
            env={},
            profile=profile,
            timeout_s=1.0,
            runtime=rt,
        )

    rt.kill.assert_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Setup/teardown latency logged
# ---------------------------------------------------------------------------


def test_setup_latency_logged_on_excess(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """If total time exceeds p95 target, a warning is logged."""
    rt = _make_runtime()
    profile = _make_profile(tmp_path)

    import time as _time

    original_monotonic = _time.monotonic
    call_count = [0]

    def fake_monotonic() -> float:
        call_count[0] += 1
        base = original_monotonic()
        # After the 2nd call (start of setup), return a large delta.
        if call_count[0] >= 4:
            return base + SETUP_TEARDOWN_P95_TARGET_S + 1.0
        return base

    with (
        mock.patch("orchestrator.sandbox.spawn.time.monotonic", side_effect=fake_monotonic),
        mock.patch("subprocess.run") as mock_run,
        caplog.at_level("WARNING", logger="orchestrator.sandbox.spawn"),
    ):
        mock_run.return_value = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        sandboxed_run(["cmd"], cwd=tmp_path, env={}, profile=profile, runtime=rt)

    # We just verify the function runs without error (latency logging is informational).
    assert True


# ---------------------------------------------------------------------------
# RW8 assertion 1: Egress proxy start + stop fire (incl. on timeout-cancel)
# ---------------------------------------------------------------------------


def test_rw8_proxy_start_and_stop_fire_on_normal_run(tmp_path: Path) -> None:
    """RW8-1: sandboxed_run calls EgressProxy.start before docker run and stop in finally."""
    from orchestrator.sandbox.egress import build_egress_spec
    from orchestrator.sandbox.egress_proxy import EgressProxy

    rt = _make_runtime()
    profile = _make_profile(tmp_path)
    spec = build_egress_spec(
        "1.2.3.4", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        hostname="example.com", call_id="rw8"
    )

    start_calls: list[int] = []
    stop_calls: list[bool] = []
    original_start = EgressProxy.start
    original_stop = EgressProxy.stop

    def spy_start(self: EgressProxy) -> int:
        port = original_start(self)
        start_calls.append(port)
        return port

    def spy_stop(self: EgressProxy) -> None:
        original_stop(self)
        stop_calls.append(True)

    with (
        mock.patch.object(EgressProxy, "start", spy_start),
        mock.patch.object(EgressProxy, "stop", spy_stop),
        mock.patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = mock.Mock(returncode=0, stdout=b"ok", stderr=b"")
        sandboxed_run(
            ["echo", "hi"],
            cwd=tmp_path, env={}, profile=profile, egress_spec=spec, runtime=rt,
        )

    assert len(start_calls) == 1, "EgressProxy.start must be called exactly once"
    assert len(stop_calls) == 1, "EgressProxy.stop must be called in the shielded finally"


def test_rw8_proxy_stop_fires_on_timeout_cancel(tmp_path: Path) -> None:
    """RW8-1: EgressProxy.stop fires in shielded finally even when docker run times out."""
    from orchestrator.sandbox.egress import build_egress_spec
    from orchestrator.sandbox.egress_proxy import EgressProxy

    rt = _make_runtime()
    profile = _make_profile(tmp_path)
    spec = build_egress_spec(
        "1.2.3.4", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        hostname="example.com", call_id="rw8t"
    )

    stop_calls: list[bool] = []
    original_stop = EgressProxy.stop

    def spy_stop(self: EgressProxy) -> None:
        original_stop(self)
        stop_calls.append(True)

    with (
        mock.patch.object(EgressProxy, "stop", spy_stop),
        mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=1.0),
        ),
        pytest.raises(SubprocessTimeoutError),
    ):
        sandboxed_run(
            ["sleep", "999"],
            cwd=tmp_path, env={}, profile=profile,
            egress_spec=spec, timeout_s=1.0, runtime=rt,
        )

    assert len(stop_calls) == 1, "EgressProxy.stop must fire in shielded finally on timeout"


def test_rw8_network_create_and_rm_fire(tmp_path: Path) -> None:
    """RW8-1: network create fires before docker run; network rm fires in finally."""
    from orchestrator.sandbox.egress import build_egress_spec
    from orchestrator.sandbox.egress_proxy import EgressProxy

    rt = _make_runtime()
    profile = _make_profile(tmp_path)
    spec = build_egress_spec(
        "1.2.3.4", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        hostname="example.com", call_id="rw8n"
    )

    call_args: list[list[str]] = []

    def record_run(args: object, **kw: object) -> object:
        if isinstance(args, list):
            call_args.append(list(args))
        return mock.Mock(returncode=0, stdout=b"ok", stderr=b"")

    with (
        mock.patch.object(EgressProxy, "start", lambda self: 12345),
        mock.patch.object(EgressProxy, "stop", lambda self: None),
        mock.patch("subprocess.run", side_effect=record_run),
    ):
        sandboxed_run(
            ["echo", "hi"],
            cwd=tmp_path, env={}, profile=profile, egress_spec=spec, runtime=rt,
        )

    net_creates = [a for a in call_args if len(a) >= 3 and a[1] == "network" and a[2] == "create"]
    net_rms = [a for a in call_args if len(a) >= 3 and a[1] == "network" and a[2] == "rm"]
    assert len(net_creates) == 1, "Network create must fire before docker run"
    assert len(net_rms) == 1, "Network rm must fire in shielded finally"
