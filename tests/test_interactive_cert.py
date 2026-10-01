"""Interactive menu (scripted answers) and the certbot-related commands with a fake certbot."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from nginx_manager import cli, interactive
from nginx_manager.cli import build_app, build_parser

from .conftest import NGINX_BIN, needs_nginx


def scripted(answers: list[str]):  # type: ignore[no-untyped-def]
    it: Iterator[str] = iter(answers)

    def prompt(text: str) -> str:
        try:
            return next(it)
        except StopIteration as exc:  # pragma: no cover - test bug guard
            raise AssertionError(f"no scripted answer for prompt {text!r}") from exc

    return prompt


def make_app(root: Path) -> cli.App:
    ns = build_parser().parse_args(
        ["--root-dir", str(root), "--nginx-bin", NGINX_BIN, "--no-reload"]
    )
    return build_app(ns)


def test_build_spec_proxy_with_everything() -> None:
    prompt = scripted(
        [
            "bad domain",
            "APP.example.com",  # domain (retry once)
            "www.example.com",  # aliases
            "8080",  # port
            "1",  # proxy mode
            "nope",
            "http://127.0.0.1:3000",  # upstream (retry once)
            "/",  # location path
            "n",  # websocket
            "y",
            "/api",
            "proxy_pass",
            "http://127.0.0.1:4000",
            "bad-name",
            "x",
            "",
            "n",  # locations
            "n",  # ssl
            "y",
            "10r/s",  # rate limit
            "",  # csp
        ]
    )
    spec = interactive.build_spec(prompt).validate()
    assert spec.domain == "app.example.com" and spec.aliases == ["www.example.com"]
    assert spec.port == 8080 and spec.websocket is False
    assert spec.locations[0].directives == [("proxy_pass", "http://127.0.0.1:4000")]
    assert spec.rate_limit == "10r/s" and spec.csp is None


def test_build_spec_static_ssl() -> None:
    prompt = scripted(
        [
            "static.example.com",
            "",
            "80",
            "2",
            "/var/www/s",
            "index.html",
            "n",  # no custom locations
            "y",
            "y",
            "y",  # ssl, redirect, hsts
            "n",  # rate limit
            "default-src 'self'",
        ]
    )
    spec = interactive.build_spec(prompt)
    assert spec.mode == "static" and spec.root == "/var/www/s"
    assert spec.ssl and spec.redirect_http and spec.hsts and spec.csp == "default-src 'self'"


def test_yes_no_defaults() -> None:
    assert interactive.yes_no("q", True, scripted([""])) is True
    assert interactive.yes_no("q", False, scripted([""])) is False
    assert interactive.yes_no("q", False, scripted(["YES"])) is True


@needs_nginx
def test_menu_full_cycle(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(root)
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    answers = [
        "1",  # list (empty)
        "2",
        "menu.example.com",
        "",
        "8080",
        "1",
        "http://127.0.0.1:3000",
        "/",
        "y",
        "n",
        "n",
        "n",
        "",
        "n",  # create: no certbot; then do_create asks confirmation
        "y",
        "3",
        "menu.example.com",  # show
        "4",
        "menu.example.com",
        "n",  # disable
        "4",
        "menu.example.com",
        "y",  # enable
        "6",
        "n",  # nginx -t, no reload
        "7",  # doctor
        "3",
        "missing.example.com",  # error path
        "zzz",  # unknown
        "5",
        "menu.example.com",
        "y",
        "n",  # delete, don't keep logs
        "q",
    ]
    prompt = scripted(answers)
    monkeypatch.setattr("builtins.input", prompt)  # ui.confirm uses input()
    rc = interactive.run_menu(app, prompt)
    out = capsys.readouterr()
    assert rc == 0
    assert "no sites in" in out.out
    assert "proxy_pass http://127.0.0.1:3000;" in out.out
    assert "unknown choice" in out.out
    assert "no site named" in out.err
    assert "checks, overall" in out.out
    assert not (root / "sites-available" / "menu.example.com.conf").exists()


@needs_nginx
def test_menu_certbot_path_with_fake_certbot(
    root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    selfsigned: tuple[Path, Path],
) -> None:
    """Fake certbot drops a certificate into letsencrypt/live/<domain>/ as the real one would."""
    cert, key = selfsigned
    live = root / "letsencrypt" / "live" / "cb.example.com"
    fake = tmp_path / "certbot"
    fake.write_text(
        f"#!/bin/sh\nmkdir -p {live}\ncp {cert} {live}/fullchain.pem\ncp {key} {live}/privkey.pem\n"
        f'echo "$@" > {tmp_path}/certbot.args\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    ns = build_parser().parse_args(
        [
            "--root-dir",
            str(root),
            "--nginx-bin",
            NGINX_BIN,
            "--no-reload",
            "--certbot-bin",
            str(fake),
        ]
    )
    app = build_app(ns)
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    answers = [
        "2",
        "cb.example.com",
        "",
        "8080",
        "1",
        "http://127.0.0.1:3000",
        "/",
        "y",
        "n",
        "n",
        "n",
        "",
        "y",
        "ops@example.com",  # certbot yes + email
        "y",  # confirm write
        "q",
    ]
    prompt = scripted(answers)
    monkeypatch.setattr("builtins.input", prompt)
    # the ssl server would listen on 443: not bindable as non-root, so steer it to 8443
    orig = interactive.build_spec
    monkeypatch.setattr(interactive, "build_spec", lambda p: _spec_8443(orig(p)))
    assert interactive.run_menu(app, prompt) == 0
    out = capsys.readouterr()
    conf = (root / "sites-available" / "cb.example.com.conf").read_text()
    assert "ssl_certificate" in conf and "return 301 https://" in conf
    assert "-d cb.example.com --email ops@example.com" in (tmp_path / "certbot.args").read_text()
    assert "written and enabled" in out.out


def _spec_8443(spec):  # type: ignore[no-untyped-def]
    spec.ssl_port = 8443
    return spec


def test_cert_command(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = tmp_path / "certbot"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    base = ["--root-dir", str(root), "--certbot-bin", str(fake)]
    rc = cli.main(
        [
            *base,
            "cert",
            "a.example.com",
            "--alias",
            "www.a.example.com",
            "--email",
            "ops@example.com",
            "--staging",
            "--yes",
        ]
    )
    out = capsys.readouterr()
    assert rc == 0 and "certificate obtained" in out.out
    assert "--staging" in out.out and "-d www.a.example.com" in out.out
    fake.write_text("#!/bin/sh\nexit 7\n")
    rc = cli.main([*base, "cert", "a.example.com", "--yes"])
    out = capsys.readouterr()
    assert rc == 6 and "exited with 7" in out.err and "no --email" in out.err
    rc = cli.main(
        [
            "--root-dir",
            str(root),
            "--certbot-bin",
            "/nonexistent/certbot",
            "cert",
            "a.example.com",
            "--yes",
        ]
    )
    assert rc == 6 and "certbot not found" in capsys.readouterr().err
    rc = cli.main([*base, "cert", "a.example.com", "--email", "bad", "--yes"])
    assert rc == 1


@needs_nginx
def test_create_with_certbot_failure_keeps_http_site(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = tmp_path / "certbot"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    rc = cli.main(
        [
            "--root-dir",
            str(root),
            "--nginx-bin",
            NGINX_BIN,
            "--no-reload",
            "--certbot-bin",
            str(fake),
            "create",
            "cb.example.com",
            "--proxy",
            "http://127.0.0.1:1",
            "--port",
            "8080",
            "--ssl-port",
            "8443",
            "--certbot",
            "--yes",
        ]
    )
    out = capsys.readouterr()
    assert rc == 6 and "HTTP-only site stays enabled" in out.err
    conf = (root / "sites-available" / "cb.example.com.conf").read_text()
    assert "ssl_certificate" not in conf and "listen 8080;" in conf


def test_create_certbot_and_cert_exclusive(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = tmp_path / "certbot"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    rc = cli.main(
        [
            "--root-dir",
            str(root),
            "--certbot-bin",
            str(fake),
            "create",
            "x.example.com",
            "--proxy",
            "http://127.0.0.1:1",
            "--certbot",
            "--cert",
            "/c",
            "--key",
            "/k",
            "--yes",
        ]
    )
    assert rc == 1 and "mutually exclusive" in capsys.readouterr().err


def test_doctor_command_exit_code(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(
        ["--root-dir", str(root / "missing"), "--nginx-bin", "/nonexistent/nginx", "doctor"]
    )
    out = capsys.readouterr().out
    assert rc == 1 and "overall: fail" in out


def test_ui_color_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    from nginx_manager import ui

    class Tty:
        @staticmethod
        def isatty() -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert ui.use_color(Tty()) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.use_color(Tty()) is False
    assert ui.paint("x", "red") == "x" or not os.isatty(1)
    assert ui.table(("A", "B"), [("1", "22")]).splitlines()[2] == "1  22"
