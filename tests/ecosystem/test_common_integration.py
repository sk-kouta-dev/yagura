"""Real-execution tests for yagura-tools-common.

Exercises the handlers against the actual filesystem + a local HTTP server.
No mocks — these actually call subprocess, read/write files, and hit HTTP.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from yagura.safety.reliability import ReliabilityLevel
from yagura.tools.executor import ToolExecutor

_executor = ToolExecutor()


async def _call(tool, **params):
    """Invoke a tool's handler uniformly whether it's sync or async."""
    return await _executor.execute(tool, params)


# ---------------------------------------------------------------------------
# File + directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_read_write_roundtrip(tmp_path: Path) -> None:
    from yagura_tools.common.file import file_read, file_write

    target = tmp_path / "subdir" / "note.txt"
    w = await _call(file_write, path=str(target), content="hello — 日本語", overwrite=True)
    assert w.success
    assert w.data["bytes_written"] > 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello — 日本語"

    r = await _call(file_read, path=str(target))
    assert r.success
    assert r.data["content"] == "hello — 日本語"
    # file_read should carry AUTHORITATIVE reliability.
    assert r.reliability is ReliabilityLevel.AUTHORITATIVE


@pytest.mark.asyncio
async def test_file_write_overwrite_guard(tmp_path: Path) -> None:
    from yagura_tools.common.file import file_write

    target = tmp_path / "keep.txt"
    target.write_text("original", encoding="utf-8")

    result = await _call(file_write, path=str(target), content="new", overwrite=False)
    assert result.success is False
    assert "already exists" in (result.error or "")
    # Original content preserved.
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_file_copy_move_delete(tmp_path: Path) -> None:
    from yagura_tools.common.file import file_copy, file_delete, file_move

    src = tmp_path / "a.txt"
    src.write_text("content", encoding="utf-8")
    copied = tmp_path / "b.txt"
    moved = tmp_path / "c.txt"

    assert (await _call(file_copy, source=str(src), destination=str(copied))).success
    assert copied.exists() and src.exists()

    assert (await _call(file_move, source=str(copied), destination=str(moved))).success
    assert moved.exists() and not copied.exists()

    assert (await _call(file_delete, path=str(moved))).success
    assert not moved.exists()


@pytest.mark.asyncio
async def test_directory_list_recursive(tmp_path: Path) -> None:
    from yagura_tools.common.directory import directory_list

    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("2")

    shallow = await _call(directory_list, path=str(tmp_path), recursive=False)
    assert shallow.success
    assert shallow.data["count"] == 2  # a.txt, sub

    deep = await _call(directory_list, path=str(tmp_path), recursive=True)
    assert deep.success
    assert deep.data["count"] == 3  # a.txt, sub, sub/b.txt


@pytest.mark.asyncio
async def test_directory_create_and_delete(tmp_path: Path) -> None:
    from yagura_tools.common.directory import directory_create, directory_delete

    target = tmp_path / "nested" / "deep"
    assert (await _call(directory_create, path=str(target), parents=True)).success
    assert target.is_dir()

    # Non-empty directory, recursive=False should fail.
    (target / "file.txt").write_text("x")
    fail = await _call(directory_delete, path=str(target), recursive=False)
    assert fail.success is False

    ok = await _call(directory_delete, path=str(target.parent), recursive=True)
    assert ok.success
    assert not target.parent.exists()


# ---------------------------------------------------------------------------
# env_get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_get(monkeypatch: pytest.MonkeyPatch) -> None:
    from yagura_tools.common.env import env_get

    monkeypatch.setenv("YAGURA_TEST_VAR", "abc")
    result = await _call(env_get, name="YAGURA_TEST_VAR")
    assert result.success
    assert result.data == {"name": "YAGURA_TEST_VAR", "value": "abc"}

    missing = await _call(env_get, name="YAGURA_NO_SUCH_VAR_12345")
    assert missing.success is False


# ---------------------------------------------------------------------------
# process_list (best-effort, depends on platform)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_list_returns_processes() -> None:
    from yagura_tools.common.process import process_list

    result = await _call(process_list, filter=None)
    assert result.success
    assert "processes" in result.data
    assert result.data["count"] > 0  # Something's always running.
    for proc in result.data["processes"][:3]:
        assert "pid" in proc
        assert "name" in proc


# ---------------------------------------------------------------------------
# shell_execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_execute_runs_trivial_command(tmp_path: Path) -> None:
    from yagura_tools.common.shell import shell_execute

    # Platform-agnostic echo.
    cmd = f"{sys.executable} -c \"print('hello')\""
    result = await _call(shell_execute, command=cmd, cwd=str(tmp_path), timeout=30)
    assert result.success
    assert "hello" in result.data["stdout"]
    assert result.data["returncode"] == 0


@pytest.mark.asyncio
async def test_shell_execute_reports_nonzero_exit() -> None:
    from yagura_tools.common.shell import shell_execute

    # Exit with code 42.
    cmd = f'{sys.executable} -c "import sys; sys.exit(42)"'
    result = await _call(shell_execute, command=cmd, cwd=None, timeout=30)
    assert result.success is False
    assert result.data["returncode"] == 42


@pytest.mark.asyncio
async def test_shell_execute_times_out() -> None:
    from yagura_tools.common.shell import shell_execute

    cmd = f'{sys.executable} -c "import time; time.sleep(5)"'
    result = await _call(shell_execute, command=cmd, cwd=None, timeout=1)
    assert result.success is False
    assert "timed out" in (result.error or "")


# ---------------------------------------------------------------------------
# http_request (against a local server so we're not network-dependent)
# ---------------------------------------------------------------------------


class _LocalHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a, **_k):  # silence HTTPServer logs in tests
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send_json({"method": "GET", "path": self.path})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = body
        self._send_json({"method": "POST", "received": parsed})

    def do_DELETE(self) -> None:
        self._send_json({"method": "DELETE", "path": self.path}, status=200)


@pytest.fixture(scope="module")
def _local_server():
    server = HTTPServer(("127.0.0.1", 0), _LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_http_request_get(_local_server: str) -> None:
    from yagura_tools.common.http import http_request

    result = await _call(http_request, url=f"{_local_server}/hello", method="GET")
    assert result.success
    assert result.data["status"] == 200
    assert result.data["body"] == {"method": "GET", "path": "/hello"}


@pytest.mark.asyncio
async def test_http_request_post_json(_local_server: str) -> None:
    from yagura_tools.common.http import http_request

    result = await _call(
        http_request,
        url=f"{_local_server}/echo",
        method="POST",
        body={"name": "yagura", "n": 42},
    )
    assert result.success
    assert result.data["body"]["received"] == {"name": "yagura", "n": 42}


@pytest.mark.asyncio
async def test_http_request_delete(_local_server: str) -> None:
    from yagura_tools.common.http import http_request

    result = await _call(http_request, url=f"{_local_server}/item/1", method="DELETE")
    assert result.success
    assert result.data["body"]["method"] == "DELETE"
