"""P4.2-B3-2: subprocess_tools.py unit tests (ADR-034 D1/D3/D5).

B3-2 acceptance tests:
  - per-tool happy path (tiny git repo / pytest file under tmp sandbox)
  - param-allowlist rejection
  - path-escape rejection
  - non-zero exit → TOOL_RESULT not TOOL_FAILED
  - timeout → subprocess_timeout in TOOL_FAILED message
  - spawn-failure → subprocess_spawn_failed in TOOL_FAILED message
  - git_log max_count clamp
  - path starting with '-' cannot become a flag
  - B3 env test: subprocess env contains PATH, no unsafe secrets
  - _is_posture_b_subprocess marker on all 5 tools
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestrator.mcp.subprocess_trust import _SAFE_ENV_KEYS, scoped_env
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.subprocess_tools import (
    _GIT_ALLOW_PROTOCOL,
    _SUBPROCESS_TIMEOUTS,
    _dispatch,
    _SubprocessToolFn,
    build_subprocess_tool_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(tmp_path: Path) -> None:
    """Initialise a minimal git repo in tmp_path."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def _invoke(tool_name: str, sandbox: Path, params: dict[str, Any]) -> Any:
    registry = build_subprocess_tool_registry(sandbox)
    return registry[tool_name](params)


# ---------------------------------------------------------------------------
# Marker: all 5 tools carry _is_posture_b_subprocess = True
# ---------------------------------------------------------------------------


def test_all_tools_have_posture_b_marker(tmp_path: Path) -> None:
    registry = build_subprocess_tool_registry(tmp_path)
    for name, fn in registry.items():
        assert getattr(fn, "_is_posture_b_subprocess", False), (
            f"{name}: missing _is_posture_b_subprocess marker"
        )
    assert all(isinstance(fn, _SubprocessToolFn) for fn in registry.values())


# ---------------------------------------------------------------------------
# Env test (B3-2): scoped_env used for subprocess, no unsafe secrets pass through
# ---------------------------------------------------------------------------


def test_b3_env_scoped_no_secrets() -> None:
    """Subprocess env has PATH (tools resolve) and no key outside _SAFE_ENV_KEYS."""
    secret_key = "B3_SUBPROCESS_ENV_SECRET_TEST"
    os.environ[secret_key] = "should_not_appear"
    try:
        env = scoped_env()
        # PATH must be present so git/ruff/pytest resolve
        assert "PATH" in env, "PATH must be in scoped env for subprocess tools to resolve"
        # No keys outside _SAFE_ENV_KEYS
        for key in env:
            assert key in _SAFE_ENV_KEYS, (
                f"Key {key!r} leaked into scoped_env() — outside _SAFE_ENV_KEYS"
            )
        # Seeded secret must be absent
        assert secret_key not in env
    finally:
        os.environ.pop(secret_key, None)


# ---------------------------------------------------------------------------
# Param allowlist rejection
# ---------------------------------------------------------------------------


def test_param_allowlist_rejects_disallowed(tmp_path: Path) -> None:
    """Disallowed params raise LocalToolError for every tool."""
    registry = build_subprocess_tool_registry(tmp_path)
    bad_params: dict[str, dict[str, Any]] = {
        "run_tests": {"--pdb": "yes"},
        "run_lint": {"-c": "import os"},
        "git_blame": {"ref": "HEAD", "path": "f.py"},
        "git_log": {"refs": "HEAD~5..HEAD"},
        "git_diff": {"cached": True},
    }
    for tool_name, params in bad_params.items():
        with pytest.raises(LocalToolError, match="disallowed"):
            registry[tool_name](params)


# ---------------------------------------------------------------------------
# Path escape rejection
# ---------------------------------------------------------------------------


def test_path_escape_rejected(tmp_path: Path) -> None:
    """Paths escaping sandbox raise LocalToolError."""
    for tool_name in ("run_tests", "run_lint", "git_blame", "git_log", "git_diff"):
        with pytest.raises(LocalToolError):
            _invoke(tool_name, tmp_path, {"path": "../../etc/passwd"})


# ---------------------------------------------------------------------------
# Path starting with '-' cannot become a flag
# ---------------------------------------------------------------------------


def test_path_starting_with_dash_cannot_be_flag(tmp_path: Path) -> None:
    """A path param starting with '-' is resolved to an abs path → cannot be a flag."""
    # '-bad' under sandbox resolves to an absolute path; the tool will call the
    # subprocess with that absolute path (which starts with '/'), not '-bad'.
    # The subprocess may fail (file doesn't exist) but it must NOT be treated as a
    # flag passthrough — the path check either resolves cleanly inside sandbox or fails.
    result = _invoke("git_diff", tmp_path, {"path": "-bad"})
    # If it succeeds, the output should NOT contain a git flag interpretation
    # (a path starting with '-' resolved to abs path '/tmp/.../bad' — not a flag)
    assert "-bad" not in result.content or result.exit_code != 0


# ---------------------------------------------------------------------------
# git_log max_count clamp
# ---------------------------------------------------------------------------


def test_git_log_max_count_clamped(tmp_path: Path) -> None:
    """max_count outside [1,100] is clamped, not rejected."""
    _git_init(tmp_path)
    (tmp_path / "f.py").write_text("x=1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Over-cap: 9999 → clamped to 100 (should not raise)
    result = _invoke("git_log", tmp_path, {"max_count": 9999})
    assert "exit_code=" in result.content
    # Under-cap: 0 → clamped to 1 (should not raise)
    result = _invoke("git_log", tmp_path, {"max_count": 0})
    assert "exit_code=" in result.content


# ---------------------------------------------------------------------------
# Happy path: run_tests
# ---------------------------------------------------------------------------


def test_run_tests_happy_path(tmp_path: Path) -> None:
    """run_tests with a passing test file → exit_code=0, TOOL_RESULT."""
    test_file = tmp_path / "test_simple.py"
    test_file.write_text("def test_ok(): assert True\n")
    result = _invoke("run_tests", tmp_path, {"path": "test_simple.py"})
    assert "exit_code=0" in result.content


def test_run_tests_nonzero_exit_is_tool_result(tmp_path: Path) -> None:
    """run_tests with a failing test → non-zero exit → TOOL_RESULT, not TOOL_FAILED."""
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_bad(): assert False\n")
    result = _invoke("run_tests", tmp_path, {"path": "test_fail.py"})
    # exit_code is in content (format: "exit_code=N\n...")
    assert "exit_code=" in result.content
    assert "exit_code=0" not in result.content  # non-zero captured, not raised


# ---------------------------------------------------------------------------
# Happy path: run_lint
# ---------------------------------------------------------------------------


def test_run_lint_happy_path(tmp_path: Path) -> None:
    """run_lint on clean file → exit_code=0."""
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n")
    result = _invoke("run_lint", tmp_path, {"path": "clean.py"})
    assert "exit_code=0" in result.content


# ---------------------------------------------------------------------------
# Happy path: git tools
# ---------------------------------------------------------------------------


def test_git_blame_happy_path(tmp_path: Path) -> None:
    """git_blame on a committed file → exit_code=0, output captured."""
    _git_init(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    result = _invoke("git_blame", tmp_path, {"path": "a.py"})
    assert "exit_code=0" in result.content


def test_git_log_happy_path(tmp_path: Path) -> None:
    """git_log after commit → exit_code=0, output captured."""
    _git_init(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: B3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    result = _invoke("git_log", tmp_path, {})
    assert "exit_code=0" in result.content
    assert "B3" in result.content


def test_git_diff_happy_path(tmp_path: Path) -> None:
    """git_diff with no changes → exit_code=0."""
    _git_init(tmp_path)
    result = _invoke("git_diff", tmp_path, {})
    assert "exit_code=0" in result.content


# ---------------------------------------------------------------------------
# Spawn failure → subprocess_spawn_failed in TOOL_FAILED message
# ---------------------------------------------------------------------------


def test_spawn_failure_raises_local_tool_error(tmp_path: Path) -> None:
    """A tool that can't spawn (bad binary) raises LocalToolError with subprocess_spawn_failed."""
    with pytest.raises(LocalToolError, match="subprocess_spawn_failed"):
        _dispatch(
            "run_lint",
            ["/nonexistent_binary_b3_test"],
            tmp_path,
            _SUBPROCESS_TIMEOUTS["run_lint"],
        )


# ---------------------------------------------------------------------------
# Timeout → subprocess_timeout in TOOL_FAILED message (B3-2 acceptance; R0-A Y1)
# ---------------------------------------------------------------------------


def test_timeout_raises_local_tool_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout from run_scoped_command → LocalToolError with subprocess_timeout in message.

    Symmetric twin of test_spawn_failure_raises_local_tool_error.
    Covers the _dispatch except-SubprocessTimeoutError branch (R0-A Y1 gap).
    """
    import orchestrator.tools.subprocess_tools as st_mod
    from orchestrator.mcp.subprocess_trust import SubprocessTimeoutError

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise SubprocessTimeoutError("timed out after 30s")

    monkeypatch.setattr(st_mod, "run_scoped_command", _raise_timeout)
    with pytest.raises(LocalToolError, match="subprocess_timeout"):
        _dispatch("run_lint", ["ruff", "check", "x.py"], tmp_path, _SUBPROCESS_TIMEOUTS["run_lint"])


# ---------------------------------------------------------------------------
# git_blame requires path
# ---------------------------------------------------------------------------


def test_git_blame_requires_path(tmp_path: Path) -> None:
    """git_blame without path → LocalToolError."""
    with pytest.raises(LocalToolError, match="'path' is required"):
        _invoke("git_blame", tmp_path, {})


# ---------------------------------------------------------------------------
# B5-3: git_push tests (ADR-036 D3-iii)
# ---------------------------------------------------------------------------


def test_git_push_is_subprocess_tool_fn(tmp_path: Path) -> None:
    """git_push carries _is_posture_b_subprocess = True."""
    fn = build_subprocess_tool_registry(tmp_path)["git_push"]
    assert getattr(fn, "_is_posture_b_subprocess", False) is True


def test_git_push_in_registry(tmp_path: Path) -> None:
    """git_push appears in build_subprocess_tool_registry keys."""
    assert "git_push" in build_subprocess_tool_registry(tmp_path)


def test_git_push_flag_shaped_remote_refused(tmp_path: Path) -> None:
    """git_push rejects remote that starts with '-' (flag-shaped)."""
    with pytest.raises(LocalToolError, match="looks like a flag"):
        _invoke("git_push", tmp_path, {"remote": "--force", "branch": "main"})


def test_git_push_flag_shaped_branch_refused(tmp_path: Path) -> None:
    """git_push rejects branch that starts with '-' (flag-shaped)."""
    with pytest.raises(LocalToolError, match="looks like a flag"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "-u"})


def test_git_push_banned_flag_as_remote_refused(tmp_path: Path) -> None:
    """git_push refuses if remote value is a banned destructive flag."""
    with pytest.raises(LocalToolError):
        _invoke("git_push", tmp_path, {"remote": "--force", "branch": "main"})


def test_git_push_disallowed_param_refused(tmp_path: Path) -> None:
    """git_push refuses params outside {remote, branch}."""
    with pytest.raises(LocalToolError, match="disallowed param"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "main", "force": True})


def test_git_push_happy_path_local_remote(tmp_path: Path) -> None:
    """git_push to a local bare remote repo succeeds; output contains exit_code."""
    import subprocess as _subprocess

    bare = tmp_path / "bare.git"
    bare.mkdir()
    _subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    src = tmp_path / "src"
    src.mkdir()
    _subprocess.run(["git", "init", "-b", "main", str(src)], check=True, capture_output=True)
    _subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        check=True,
        cwd=str(src),
        capture_output=True,
    )
    _subprocess.run(
        ["git", "config", "user.name", "Test"], check=True, cwd=str(src), capture_output=True
    )
    _subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        check=True,
        cwd=str(src),
        capture_output=True,
    )
    (src / "f.txt").write_text("hello")
    _subprocess.run(["git", "add", "."], check=True, cwd=str(src), capture_output=True)
    _subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=str(src), capture_output=True)

    result = _invoke("git_push", src, {"remote": "origin", "branch": "main"})
    assert "exit_code=0" in result.content, (
        f"push must succeed (exit_code=0), got: {result.content!r}"
    )


def test_git_push_ssh_auth_sock_overlaid_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSH_AUTH_SOCK is passed to subprocess env when present in os.environ."""
    import orchestrator.tools.subprocess_tools as st_mod

    captured_env: dict[str, str] = {}

    def _fake_scoped_env(
        extra_env: dict[str, str] | None = None, api_key_env: str | None = None
    ) -> dict[str, str]:
        env = {k: "x" for k in _SAFE_ENV_KEYS}
        if extra_env:
            env.update(extra_env)
        captured_env.update(env)
        return env

    monkeypatch.setattr(st_mod, "scoped_env", _fake_scoped_env)

    fake_sock = "/tmp/fake_ssh_agent.sock"
    monkeypatch.setenv("SSH_AUTH_SOCK", fake_sock)

    # Mock run_scoped_command to avoid real subprocess
    from orchestrator.mcp.subprocess_trust import SubprocessTimeoutError  # noqa: F401

    class FakeResult:
        exit_code = 0
        output = "pushed"
        truncated = False

    def _fake_run(*args: Any, **kwargs: Any) -> FakeResult:
        argv = list(args[0]) if args else []
        if argv == ["git", "remote"]:
            r = FakeResult()
            r.output = "origin\n"
            return r
        return FakeResult()

    monkeypatch.setattr(st_mod, "run_scoped_command", _fake_run)

    _invoke("git_push", tmp_path, {"remote": "origin", "branch": "main"})
    assert captured_env.get("SSH_AUTH_SOCK") == fake_sock, (
        "SSH_AUTH_SOCK was not passed to subprocess env when present"
    )


def test_git_push_ssh_auth_sock_absent_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When SSH_AUTH_SOCK is absent from os.environ, it is NOT injected into subprocess env."""
    import orchestrator.tools.subprocess_tools as st_mod

    captured_env: dict[str, str] = {}

    def _fake_scoped_env(
        extra_env: dict[str, str] | None = None, api_key_env: str | None = None
    ) -> dict[str, str]:
        env = {k: "x" for k in _SAFE_ENV_KEYS}
        if extra_env:
            env.update(extra_env)
        captured_env.update(env)
        return env

    monkeypatch.setattr(st_mod, "scoped_env", _fake_scoped_env)
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)

    class FakeResult:
        exit_code = 0
        output = "pushed"
        truncated = False

    def _fake_run(*args: Any, **kwargs: Any) -> FakeResult:
        argv = list(args[0]) if args else []
        if argv == ["git", "remote"]:
            r = FakeResult()
            r.output = "origin\n"
            return r
        return FakeResult()

    monkeypatch.setattr(st_mod, "run_scoped_command", _fake_run)

    _invoke("git_push", tmp_path, {"remote": "origin", "branch": "main"})
    assert "SSH_AUTH_SOCK" not in captured_env, (
        "SSH_AUTH_SOCK injected into env even when absent from os.environ"
    )


def test_git_push_result_excluded_from_excerpt(tmp_path: Path) -> None:
    """git_push TOOL_RESULT is absent from snapshot_excerpt (b35 behavioral extension).

    git_push joins _SUBPROCESS_TOOL_NAMES; its remote-controlled output should not
    appear in the steering excerpt.
    """
    from orchestrator.agents.selection import _render_snapshot_excerpt
    from orchestrator.core.event import (
        Event,
        EventType,
        generate_event_id,
        generate_room_id,
        now_ms,
    )

    injection = "GIT_PUSH_CANARY_INJECTION_DO_NOT_RENDER"
    rid = generate_room_id()

    tc = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata={"tool_name": "git_push", "call_id": "cid_push_1", "params": {}},
    )
    tr = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content=injection,
        metadata={"call_id": "cid_push_1", "success": True},
    )
    snapshot = [tc, tr]
    excerpt = _render_snapshot_excerpt(snapshot)
    assert excerpt is None or injection not in excerpt, (
        f"git_push TOOL_RESULT appeared in snapshot_excerpt: {excerpt!r}"
    )


# ---------------------------------------------------------------------------
# P6.5-G1: transport allowlist + configured-remote restriction tests
# ---------------------------------------------------------------------------


def test_git_push_ext_transport_remote_rejected(tmp_path: Path) -> None:
    """ext:: remote is rejected as not a configured remote name (LocalToolError, no PWNED)."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    _git_init(src)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=src,
        check=True,
        capture_output=True,
    )
    (src / "f.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=src, check=True, capture_output=True)

    pwned = tmp_path / "PWNED"
    with pytest.raises(LocalToolError, match="not a configured remote"):
        _invoke("git_push", src, {"remote": f"ext::sh -c 'touch {pwned}'", "branch": "main"})
    assert not pwned.exists(), "PWNED file must not be created"


def test_git_push_inline_url_remote_rejected(tmp_path: Path) -> None:
    """Inline https:// URL is rejected as not a configured remote name (LocalToolError)."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    _git_init(src)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=src,
        check=True,
        capture_output=True,
    )
    with pytest.raises(LocalToolError, match="not a configured remote"):
        _invoke("git_push", src, {"remote": "https://evil/r", "branch": "main"})


def test_git_push_ext_protocol_blocked_by_allowlist(tmp_path: Path) -> None:
    """A configured remote with ext:: URL is blocked by GIT_ALLOW_PROTOCOL (defense-in-depth)."""
    src = tmp_path / "src"
    src.mkdir()
    _git_init(src)
    (src / "f.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=src, check=True, capture_output=True)
    pwned = tmp_path / "PWNED"
    subprocess.run(
        ["git", "remote", "add", "evil", f"ext::sh -c 'touch {pwned}'"],
        cwd=src,
        check=True,
        capture_output=True,
    )
    # Remote name passes the configured-remote check; GIT_ALLOW_PROTOCOL blocks ext:: transport.
    result = _invoke("git_push", src, {"remote": "evil", "branch": "main"})
    assert not pwned.exists(), "PWNED file must not be created (ext:: transport denied)"
    assert "not allowed" in result.content, (
        "GIT_ALLOW_PROTOCOL must produce 'not allowed' denial (fails on revert of allowlist)"
    )


def test_git_push_allow_protocol_in_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GIT_ALLOW_PROTOCOL is present in subprocess env for git_push."""
    import orchestrator.tools.subprocess_tools as st_mod

    captured_env: dict[str, str] = {}

    def _fake_scoped_env(
        extra_env: dict[str, str] | None = None, api_key_env: str | None = None
    ) -> dict[str, str]:
        env = {k: "x" for k in _SAFE_ENV_KEYS}
        if extra_env:
            env.update(extra_env)
        captured_env.update(env)
        return env

    monkeypatch.setattr(st_mod, "scoped_env", _fake_scoped_env)

    class FakeResult:
        exit_code = 0
        output = "pushed"
        truncated = False

    def _fake_run(*args: Any, **kwargs: Any) -> FakeResult:
        argv = list(args[0]) if args else []
        if argv == ["git", "remote"]:
            r = FakeResult()
            r.output = "origin\n"
            return r
        return FakeResult()

    monkeypatch.setattr(st_mod, "run_scoped_command", _fake_run)

    _invoke("git_push", tmp_path, {"remote": "origin", "branch": "main"})
    assert captured_env.get("GIT_ALLOW_PROTOCOL") == _GIT_ALLOW_PROTOCOL, (
        "GIT_ALLOW_PROTOCOL was not passed to subprocess env"
    )


# ---------------------------------------------------------------------------
# P6.5 cycle-2: refspec bypass rejection (R0-B R1/R2) + allowlist regression (R0-A Y1)
# ---------------------------------------------------------------------------


def test_git_push_transport_allowlist_set() -> None:
    """_GIT_ALLOW_PROTOCOL includes file (local pushes) and excludes ext (RCE vector)."""
    allowed = set(_GIT_ALLOW_PROTOCOL.split(":"))
    assert "https" in allowed
    assert "ssh" in allowed
    assert "git" in allowed
    assert "file" in allowed, "file transport must be in allowlist (local-remote pushes need it)"
    assert "ext" not in allowed, "ext transport must NOT be in allowlist (RCE vector)"


def test_git_push_refspec_delete_rejected(tmp_path: Path) -> None:
    """branch=':main' is a deletion refspec — rejected before argv build; remote ref intact."""
    import subprocess as _subprocess

    bare = tmp_path / "bare.git"
    bare.mkdir()
    _subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    src = tmp_path / "src"
    src.mkdir()
    _subprocess.run(["git", "init", "-b", "main", str(src)], check=True, capture_output=True)
    for cmd in (
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
    ):
        _subprocess.run(cmd, cwd=str(src), check=True, capture_output=True)
    _subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(src),
        check=True,
        capture_output=True,
    )
    (src / "f.txt").write_text("hello")
    _subprocess.run(["git", "add", "."], cwd=str(src), check=True, capture_output=True)
    _subprocess.run(["git", "commit", "-m", "init"], cwd=str(src), check=True, capture_output=True)
    _subprocess.run(
        ["git", "push", "origin", "main"], cwd=str(src), check=True, capture_output=True
    )

    with pytest.raises(LocalToolError, match=r"glob \(\*\) refspecs are rejected"):
        _invoke("git_push", src, {"remote": "origin", "branch": ":main"})

    ls = _subprocess.run(
        ["git", "ls-remote", str(bare), "refs/heads/main"],
        capture_output=True,
        text=True,
    )
    assert ls.stdout.strip(), "remote main ref must still exist after rejected deletion refspec"


def test_git_push_refspec_force_push_rejected(tmp_path: Path) -> None:
    """branch='+main:main' is a force-push refspec — rejected before argv build."""
    with pytest.raises(LocalToolError, match=r"glob \(\*\) refspecs are rejected"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "+main:main"})


# P6.9-110: glob (*) refspec rejection + accurate guard message


def test_git_push_glob_refspec_rejected(tmp_path: Path) -> None:
    """branch containing '*' (glob) is rejected before argv build (P6.9-#110)."""
    with pytest.raises(LocalToolError, match=r"glob \(\*\) refspecs are rejected"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "refs/heads/*:refs/heads/*"})


def test_git_push_glob_star_alone_rejected(tmp_path: Path) -> None:
    """branch='*' (bare glob) is rejected (P6.9-#110)."""
    with pytest.raises(LocalToolError, match=r"glob \(\*\) refspecs are rejected"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "*"})


def test_git_push_glob_in_src_dst_rejected(tmp_path: Path) -> None:
    """branch='main:*' (glob in dst) is rejected (P6.9-#110)."""
    with pytest.raises(LocalToolError, match=r"glob \(\*\) refspecs are rejected"):
        _invoke("git_push", tmp_path, {"remote": "origin", "branch": "main:*"})


def test_git_push_simple_src_dst_not_over_blocked(tmp_path: Path) -> None:
    """branch='main:other' (simple src:dst, no glob) must not be blocked by the
    glob/prefix guard (P6.9-#110 no-over-block invariant)."""
    import subprocess as _subprocess

    bare = tmp_path / "bare.git"
    bare.mkdir()
    _subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    src = tmp_path / "src"
    src.mkdir()
    _subprocess.run(["git", "init", "-b", "main", str(src)], check=True, capture_output=True)
    for cmd in (
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
    ):
        _subprocess.run(cmd, cwd=str(src), check=True, capture_output=True)
    _subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(src),
        check=True,
        capture_output=True,
    )
    (src / "f.txt").write_text("hello")
    _subprocess.run(["git", "add", "."], cwd=str(src), check=True, capture_output=True)
    _subprocess.run(["git", "commit", "-m", "init"], cwd=str(src), check=True, capture_output=True)

    try:
        _invoke("git_push", src, {"remote": "origin", "branch": "main:other"})
    except LocalToolError as exc:
        msg = str(exc)
        assert "glob" not in msg and "refspec prefix" not in msg, (
            f"test_git_push_simple_src_dst_not_over_blocked: "
            f"main:other raised the glob/prefix guard unexpectedly: {msg!r}"
        )
