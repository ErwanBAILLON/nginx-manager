"""End-to-end tests: the CLI writes into a temp prefix and the real nginx binary validates it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nginx_manager import cli

from .conftest import needs_nginx

pytestmark = needs_nginx

PROXY = ("create", "app.example.com", "--proxy", "http://127.0.0.1:3000", "--port", "8080", "--yes")


def _nginx_t(run) -> None:  # type: ignore[no-untyped-def]
    rc, out, _ = run("test")
    assert rc == 0, out
    assert "test is successful" in out


def test_proxy_site_passes_nginx_t(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    rc, out, err = run(
        *PROXY,
        "--location",
        "/api:proxy_pass=http://127.0.0.1:4000",
        "--location",
        "/api:proxy_set_header=Host $host",
    )
    assert rc == 0, err
    assert "# managed by nginx-manager v" in out
    conf = root / "sites-available" / "app.example.com.conf"
    assert conf.is_file()
    link = root / "sites-enabled" / "app.example.com.conf"
    assert link.is_symlink() and link.resolve() == conf.resolve()
    assert (root / "conf.d" / "nginx-manager.conf").is_file()
    assert (root / "snippets" / "nginx-manager" / "app.example.com.headers.conf").is_file()
    assert (root / "log" / "app.example.com").is_dir()
    _nginx_t(run)


def test_static_site_passes_nginx_t(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    rc, _, err = run(
        "create",
        "www.example.org",
        "--static",
        str(root / "www"),
        "--port",
        "8081",
        "--index",
        "index.html index.htm",
        "--yes",
    )
    assert rc == 0, err
    _nginx_t(run)


def test_ssl_redirect_hsts_ratelimit(run, root: Path, selfsigned: tuple[Path, Path]) -> None:  # type: ignore[no-untyped-def]
    cert, key = selfsigned
    rc, out, err = run(
        *PROXY,
        "--ssl",
        "--ssl-port",
        "8443",
        "--cert",
        str(cert),
        "--key",
        str(key),
        "--redirect-http",
        "--hsts",
        "--rate-limit",
        "10r/s",
        "--csp",
        "default-src 'self'",
    )
    assert rc == 0, err
    assert "return 301 https://$host$request_uri;" in out
    assert "limit_req zone=nm_app_example_com" in out
    zones = (root / "conf.d" / "nginx-manager.conf").read_text()
    assert "zone=nm_app_example_com:10m rate=10r/s;" in zones
    snippet = (root / "snippets" / "nginx-manager" / "app.example.com.headers.conf").read_text()
    assert "Strict-Transport-Security" in snippet and "Content-Security-Policy" in snippet
    _nginx_t(run)

    # Replacing the site without rate limiting removes its zone and keeps a backup.
    rc, _, err = run(
        *PROXY, "--ssl", "--ssl-port", "8443", "--cert", str(cert), "--key", str(key), "--force"
    )
    assert rc == 0, err
    assert "nm_app_example_com" not in (root / "conf.d" / "nginx-manager.conf").read_text()
    backups = list((root / "sites-available" / ".nginx-manager-backups").iterdir())
    assert any(b.name.startswith("app.example.com.conf.") for b in backups)
    _nginx_t(run)


def test_ssl_without_certificate_is_refused_before_writing(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    rc, _, err = run(*PROXY, "--ssl", "--ssl-port", "8443")
    assert rc == 5
    assert "certificate file missing" in err
    assert not (root / "sites-available" / "app.example.com.conf").exists()


def test_invalid_config_is_rolled_back(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    # proxy_pass with an http:// URL in a location that also sets a non-existent directive
    rc, _, err = run(*PROXY, "--location", "/x:no_such_directive=1")
    assert rc == 3
    assert "rolled back" in err
    assert not (root / "sites-available" / "app.example.com.conf").exists()
    assert not (root / "sites-enabled" / "app.example.com.conf").exists()
    assert not (root / "snippets" / "nginx-manager" / "app.example.com.headers.conf").exists()
    _nginx_t(run)


def test_rollback_restores_previous_version(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    assert run(*PROXY)[0] == 0
    conf = root / "sites-available" / "app.example.com.conf"
    before = conf.read_text()
    rc, _, _ = run(*PROXY, "--force", "--location", "/x:no_such_directive=1")
    assert rc == 3
    assert conf.read_text() == before
    assert (root / "sites-enabled" / "app.example.com.conf").is_symlink()
    _nginx_t(run)


def test_list_show_enable_disable_delete(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    rc, out, _ = run("list")
    assert rc == 0 and "no sites" in out
    assert run(*PROXY)[0] == 0
    assert (
        run(
            "create",
            "www.example.org",
            "--static",
            str(root / "www"),
            "--port",
            "8081",
            "--yes",
            "--no-enable",
        )[0]
        == 0
    )

    rc, out, _ = run("list")
    assert rc == 0
    assert "app.example.com" in out and "proxy" in out and "static" in out
    rc, out, _ = run("list", "--json")
    data = json.loads(out)
    assert {d["name"]: d["enabled"] for d in data} == {
        "app.example.com": True,
        "www.example.org": False,
    }

    rc, out, _ = run("show", "app.example.com")
    assert rc == 0 and "proxy_pass http://127.0.0.1:3000;" in out
    rc, out, _ = run("show", "app.example.com.conf", "--explain")
    assert (
        rc == 0 and "upstream     : http://127.0.0.1:3000" in out and "kind         : proxy" in out
    )
    rc, _, err = run("show", "nope.example.com")
    assert rc == 5 and "no site named" in err

    rc, _, _ = run("disable", "app.example.com")
    assert rc == 0 and not (root / "sites-enabled" / "app.example.com.conf").exists()
    rc, _, _ = run("disable", "app.example.com")  # idempotent
    assert rc == 0
    rc, _, _ = run("enable", "app.example.com")
    assert rc == 0 and (root / "sites-enabled" / "app.example.com.conf").is_symlink()
    rc, _, _ = run("enable", "www.example.org")
    assert rc == 0
    _nginx_t(run)

    (root / "log" / "app.example.com" / "access.log").write_text("x\n")
    rc, out, _ = run("delete", "app.example.com", "--yes")
    assert rc == 0 and "deleted" in out
    assert not (root / "sites-available" / "app.example.com.conf").exists()
    assert not (root / "sites-enabled" / "app.example.com.conf").exists()
    assert not (root / "log" / "app.example.com").exists()
    rc, _, _ = run("delete", "www.example.org", "--yes", "--keep-logs")
    assert rc == 0 and (root / "log" / "www.example.org").is_dir()
    assert run("delete", "www.example.org", "--yes")[0] == 5
    _nginx_t(run)


def test_dry_run_writes_nothing(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    rc, out, err = run(*PROXY, "--dry-run")
    assert rc == 0 and "server {" in out and "dry-run" in err
    assert not list((root / "sites-available").iterdir())


def test_existing_site_needs_force(run) -> None:  # type: ignore[no-untyped-def]
    assert run(*PROXY)[0] == 0
    rc, _, err = run(*PROXY)
    assert rc == 1 and "--force" in err


def test_validation_errors_exit_1(run) -> None:  # type: ignore[no-untyped-def]
    rc, _, err = run("create", "bad domain", "--proxy", "http://x", "--yes")
    assert rc == 1 and "invalid domain" in err
    rc, _, err = run("create", "a.example.com", "--proxy", "localhost:3000", "--yes")
    assert rc == 1 and "invalid upstream" in err
    rc, _, err = run("create", "a.example.com", "--static", "relative", "--yes")
    assert rc == 1 and "absolute" in err
    rc, _, err = run("create", "a.example.com", "--proxy", "http://x", "--hsts", "--yes")
    assert rc == 1 and "require --ssl" in err


def test_confirmation_refused_without_tty(run, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    with pytest.raises(SystemExit, match="--yes"):
        run("create", "a.example.com", "--proxy", "http://127.0.0.1:1", "--port", "8080")


def test_confirmation_cancel(run, monkeypatch: pytest.MonkeyPatch, root: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    answers = iter(["maybe", "n"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    rc, out, _ = run("create", "a.example.com", "--proxy", "http://127.0.0.1:1", "--port", "8080")
    assert rc == 1 and "cancelled" in out
    assert not list((root / "sites-available").iterdir())


def test_test_and_reload_commands(run, root: Path) -> None:  # type: ignore[no-untyped-def]
    _nginx_t(run)
    (root / "sites-enabled" / "broken.conf").write_text("server { listen 8099; bogus; }\n")
    rc, _, err = run("test")
    assert rc == 3 and "nginx -t failed" in err
    (root / "sites-enabled" / "broken.conf").unlink()
    # reload: there is no running master process in the temp prefix, so it must fail cleanly
    rc, _, err = run("reload")
    assert rc == 3 and "reload failed" in err


def test_version_and_missing_nginx(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    rc = cli.main(["--root-dir", str(root), "--nginx-bin", "/nonexistent/nginx", "test"])
    assert rc == 6 and "nginx binary not found" in capsys.readouterr().err
