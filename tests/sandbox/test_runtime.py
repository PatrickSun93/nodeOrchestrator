"""Tests for sandbox/runtime.py (P4.3-1).

All tests mock subprocess so no live daemon is required.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from orchestrator.sandbox.runtime import (
    LIVENESS_PROBE_TIMEOUT_S,
    SandboxRuntime,
    SandboxUnavailableError,
    detect,
)


def _make_runtime(kind: str = "docker", cli: str = "/usr/bin/docker") -> SandboxRuntime:
    return SandboxRuntime(kind=kind, cli=cli)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# available() — liveness, not CLI presence
# ---------------------------------------------------------------------------


def test_available_true_when_info_succeeds() -> None:
    rt = _make_runtime()
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        assert rt.available() is True
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[1] == "info"


def test_available_false_when_info_nonzero() -> None:
    rt = _make_runtime()
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=1)
        assert rt.available() is False


def test_available_false_when_daemon_raises_oserror() -> None:
    rt = _make_runtime()
    with mock.patch("subprocess.run", side_effect=OSError("no daemon")):
        assert rt.available() is False


def test_available_bounded_when_probe_hangs() -> None:
    """available() must not hang; probe timeout bounds the call."""
    rt = _make_runtime()
    timeout_exc = subprocess.TimeoutExpired(
        cmd=["docker", "info"], timeout=LIVENESS_PROBE_TIMEOUT_S
    )
    with mock.patch("subprocess.run", side_effect=timeout_exc):
        result = rt.available()
    assert result is False


def test_available_false_never_raises() -> None:
    """available() must never propagate any exception."""
    rt = _make_runtime()
    with mock.patch("subprocess.run", side_effect=RuntimeError("unexpected")):
        result = rt.available()
    assert result is False


# ---------------------------------------------------------------------------
# detect() — podman preferred, first live wins
# ---------------------------------------------------------------------------


def test_detect_podman_preferred() -> None:
    with (
        mock.patch("shutil.which", side_effect=lambda k: f"/usr/bin/{k}"),
        mock.patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = mock.Mock(returncode=0)
        rt = detect()
    assert rt is not None
    assert rt.kind == "podman"


def test_detect_falls_back_to_docker_when_podman_dead() -> None:
    def which_side(name: str) -> str:
        return f"/usr/bin/{name}"

    def run_side(cmd: list[str], **kwargs: object) -> mock.Mock:
        cli = cmd[0]
        if "podman" in cli:
            return mock.Mock(returncode=1)
        return mock.Mock(returncode=0)

    with (
        mock.patch("shutil.which", side_effect=which_side),
        mock.patch("subprocess.run", side_effect=run_side),
    ):
        rt = detect()
    assert rt is not None
    assert rt.kind == "docker"


def test_detect_returns_none_when_both_absent() -> None:
    with mock.patch("shutil.which", return_value=None):
        rt = detect()
    assert rt is None


def test_detect_returns_none_when_cli_present_but_daemon_down() -> None:
    with (
        mock.patch("shutil.which", side_effect=lambda k: f"/usr/bin/{k}"),
        mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=LIVENESS_PROBE_TIMEOUT_S),
        ),
    ):
        rt = detect()
    assert rt is None


def test_detect_probe_hangs_bounded_by_timeout() -> None:
    """detect() must return even when probe hangs (bounded by timeout)."""
    with (
        mock.patch("shutil.which", side_effect=lambda k: f"/usr/bin/{k}"),
        mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=LIVENESS_PROBE_TIMEOUT_S),
        ),
    ):
        rt = detect()
    assert rt is None


# ---------------------------------------------------------------------------
# SandboxUnavailableError — importable
# ---------------------------------------------------------------------------


def test_sandbox_unavailable_error_is_exception() -> None:
    exc = SandboxUnavailableError("runtime not available")
    assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# kill() — best-effort, swallows errors
# ---------------------------------------------------------------------------


def test_kill_calls_kill_then_rm() -> None:
    rt = _make_runtime()
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        rt.kill("abc123")
    calls = [call[0][0] for call in mock_run.call_args_list]
    assert any("kill" in c for c in calls)
    assert any("rm" in c for c in calls)


def test_kill_swallows_errors() -> None:
    rt = _make_runtime()
    with mock.patch("subprocess.run", side_effect=OSError("no such container")):
        rt.kill("deadbeef")
