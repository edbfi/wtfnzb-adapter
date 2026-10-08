"""Start the adapter with a dummy config and check /health and caps; no upstream access."""

import http.client
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import cast

import msgspec
from defusedxml import ElementTree

API_KEY = "smoke-test-adapter-key-0123456789"
STARTUP_SECONDS = 30
SHUTDOWN_SECONDS = 15


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return cast("tuple[str, int]", sock.getsockname())[1]


def get(port: int, path: str) -> tuple[int, str, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        media_type = (response.getheader("Content-Type") or "").split(";")[0].strip()
        return response.status, media_type, response.read()
    finally:
        connection.close()


def wait_for_health(port: int, server: subprocess.Popen[bytes]) -> bytes:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise SystemExit(f"smoke: server exited early with {server.returncode}")
        try:
            status, _, body = get(port, "/health")
        except OSError:
            time.sleep(0.25)
            continue
        if status != 200:
            raise SystemExit(f"smoke: /health returned {status}")
        return body
    raise SystemExit(f"smoke: no /health response within {STARTUP_SECONDS} s")


def check(port: int, server: subprocess.Popen[bytes]) -> None:
    health = msgspec.json.decode(wait_for_health(port, server), type=dict[str, str])
    if health != {"status": "ok", "scope": "experimental"}:
        raise SystemExit(f"smoke: unexpected /health body {health!r}")

    status, media_type, body = get(port, f"/api?t=caps&apikey={API_KEY}")
    root = ElementTree.fromstring(body)
    modes = {mode.tag for mode in root.iterfind("searching/*")}
    if (
        status != 200
        or media_type != "application/xml"
        or root.tag != "caps"
        or modes != {"search", "tv-search", "movie-search"}
        or root.find("categories/category") is None
    ):
        raise SystemExit(f"smoke: unexpected caps response {status} {media_type} {body[:200]!r}")

    status, _, body = get(port, "/api?t=caps&apikey=wrong-key")
    if status != 401 or ElementTree.fromstring(body).get("code") != "100":
        raise SystemExit(f"smoke: a wrong API key returned {status} {body[:200]!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wtfnzb-smoke-") as tmp:
        work = Path(tmp)
        auth = work / "auth.json"
        descriptor = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(
                msgspec.json.encode(
                    {
                        "base_url": "https://wtfnzb.invalid",
                        "api_key": "dummy",
                        "user_id": "1",
                        "session": "dummy",
                    }
                )
            )
        port = free_port()
        env = {
            **os.environ,
            "ADAPTER_API_KEY": API_KEY,
            "ADAPTER_PUBLIC_URL": f"http://127.0.0.1:{port}",
            "ADAPTER_STATE_DIR": str(work / "state"),
            "WTFNZB_AUTH_FILE": str(auth),
            "WTFNZB_SITE_TIMEZONE": "Europe/Copenhagen",
            "WTFNZB_AUTO_SESSION": "false",
        }
        command = [
            *(sys.executable, "-m", "litestar", "--app", "wtfnzb_adapter.app:create_app"),
            *("run", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"),
        ]
        # The work directory has no .env, so a developer's local one can't leak in.
        server = subprocess.Popen(command, cwd=work, env=env)
        try:
            check(port, server)
            server.send_signal(signal.SIGTERM)
            code = server.wait(timeout=SHUTDOWN_SECONDS)
        finally:
            # `litestar run` starts Granian in its own process group and stops it
            # only on SIGTERM; a kill would orphan the server.
            if server.poll() is None:
                server.send_signal(signal.SIGTERM)
                try:
                    _ = server.wait(timeout=SHUTDOWN_SECONDS)
                except subprocess.TimeoutExpired:
                    server.kill()
                    _ = server.wait()
        if code != 0:
            raise SystemExit(f"smoke: server exited with {code} after SIGTERM")
    print("smoke: /health and caps passed; server shut down cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
