"""Shared fixtures: a throwaway nginx prefix that the real nginx binary can test as non-root."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nginx_manager import cli
from nginx_manager.fs import Paths
from nginx_manager.manager import Manager
from nginx_manager.nginx import Nginx
from nginx_manager.templates import RenderContext

NGINX_BIN = shutil.which("nginx") or "/usr/sbin/nginx"
HAS_NGINX = Path(NGINX_BIN).exists()
HAS_OPENSSL = shutil.which("openssl") is not None
needs_nginx = pytest.mark.skipif(not HAS_NGINX, reason="nginx binary not available")
needs_openssl = pytest.mark.skipif(not HAS_OPENSSL, reason="openssl not available")

MIME_TYPES = "types { text/html html; text/css css; application/javascript js; image/png png; }"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A minimal nginx prefix: nginx.conf with pid/error_log inside tmp, includes our dirs."""
    r = tmp_path / "nginx"
    for d in ("sites-available", "sites-enabled", "conf.d", "log", "tmp", "www"):
        (r / d).mkdir(parents=True)
    (r / "mime.types").write_text(MIME_TYPES + "\n")
    (r / "www" / "index.html").write_text("<h1>hello</h1>\n")
    (r / "nginx.conf").write_text(
        f"""pid {r}/nginx.pid;
error_log {r}/log/error.log;
events {{ worker_connections 64; }}
http {{
    include {r}/mime.types;
    access_log {r}/log/access.log;
    client_body_temp_path {r}/tmp;
    proxy_temp_path {r}/tmp;
    fastcgi_temp_path {r}/tmp;
    uwsgi_temp_path {r}/tmp;
    scgi_temp_path {r}/tmp;
    include {r}/conf.d/*.conf;
    include {r}/sites-enabled/*;
}}
"""
    )
    return r


@pytest.fixture
def paths(root: Path) -> Paths:
    return Paths.build(root=root)


@pytest.fixture
def manager(paths: Paths) -> Manager:
    return Manager(paths, Nginx(NGINX_BIN, paths.root), reload=False)


@pytest.fixture
def selfsigned(root: Path) -> tuple[Path, Path]:
    if not HAS_OPENSSL:
        pytest.skip("openssl not available")
    certs = root / "certs"
    certs.mkdir()
    cert, key = certs / "fullchain.pem", certs / "privkey.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "30",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=app.example.com",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


@pytest.fixture
def fixed_ctx(root: Path) -> RenderContext:
    """Deterministic context for golden-file comparisons."""
    return RenderContext(
        nginx_version=(1, 24, 0),
        system_resolvers=["127.0.0.53"],
        headers_snippet_dir="/etc/nginx/snippets/nginx-manager",
        log_dir="/var/log/nginx",
        letsencrypt_dir="/etc/letsencrypt",
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        version="2.0.0",
    )


@pytest.fixture
def run(root: Path, capsys: pytest.CaptureFixture[str]):  # type: ignore[no-untyped-def]
    """Invoke the CLI as a user would, against the temp root, returning (rc, stdout, stderr)."""

    def _run(*args: str) -> tuple[int, str, str]:
        rc = cli.main(["--root-dir", str(root), "--nginx-bin", NGINX_BIN, "--no-reload", *args])
        out = capsys.readouterr()
        return rc, out.out, out.err

    return _run
