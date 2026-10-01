"""Manager parsing helpers, doctor checks, nginx/certbot helpers (no nginx -t needed here)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nginx_manager import certbot, doctor
from nginx_manager.errors import MissingToolError
from nginx_manager.manager import Manager, explain, parse_site
from nginx_manager.nginx import CommandResult, Nginx, parse_version, system_resolvers
from nginx_manager.spec import SiteSpec

from .conftest import HAS_OPENSSL, NGINX_BIN, needs_nginx

HANDWRITTEN = """server {
    listen 80;
    listen [::]:443 ssl http2;
    server_name foo.example.com bar.example.com;
    root /srv/foo;
    location / { try_files $uri =404; }
}
"""


def test_parse_site_handwritten() -> None:
    info = parse_site("foo", HANDWRITTEN, enabled=False)
    assert info.server_names == ["foo.example.com", "bar.example.com"]
    assert info.ports == ["80", "443"]
    assert info.kind == "static" and info.ssl and not info.managed and not info.enabled
    assert parse_site("x", "server { listen 81; return 404; }", True).kind == "other"


def test_explain_handwritten() -> None:
    lines = explain(HANDWRITTEN)
    assert "server names : foo.example.com bar.example.com" in lines
    assert "document root: /srv/foo" in lines
    assert "tls          : yes" in lines
    assert "managed      : no" in lines
    assert any(line.startswith("locations    : /") for line in lines)


def test_list_sites_includes_unmanaged_and_missing_dir(manager: Manager, tmp_path: Path) -> None:
    (manager.paths.sites_available / "legacy").write_text(HANDWRITTEN)
    sites = manager.list_sites()
    assert [s.name for s in sites] == ["legacy"]
    assert manager.read_site("legacy") == HANDWRITTEN
    assert manager.load_spec("legacy") is None
    empty = Manager(manager.paths.__class__.build(root=tmp_path / "none"), manager.nginx)
    assert empty.list_sites() == []


def test_zones_parsing(manager: Manager) -> None:
    manager.paths.conf_d.mkdir(exist_ok=True)
    manager.paths.managed_conf.write_text(
        "map $http_upgrade $connection_upgrade { default upgrade; '' close; }\n"
        "limit_req_zone $binary_remote_addr zone=nm_a:10m rate=1r/s;  # site: a\n"
        "limit_req_zone $binary_remote_addr zone=nm_b:10m rate=2r/s;  # site: b\n"
        "garbage line\n"
    )
    assert manager._zones() == {
        "a": "limit_req_zone $binary_remote_addr zone=nm_a:10m rate=1r/s;",
        "b": "limit_req_zone $binary_remote_addr zone=nm_b:10m rate=2r/s;",
    }


def test_preflight_static_root(manager: Manager) -> None:
    spec = SiteSpec(domain="s.example.com", mode="static", root="/nonexistent/dir").validate()
    assert any("static root does not exist" in w for w in manager.preflight(spec))


def test_render_context_detects_certbot_files(manager: Manager) -> None:
    le = manager.paths.letsencrypt_dir
    le.mkdir(parents=True)
    (le / "options-ssl-nginx.conf").write_text("ssl_protocols TLSv1.2 TLSv1.3;\n")
    ctx = manager.render_context()
    assert ctx.ssl_options_file == str(le / "options-ssl-nginx.conf")
    assert ctx.ssl_dhparam_file is None


# ---------------------------------------------------------------------- nginx
def test_parse_version() -> None:
    assert parse_version("nginx version: nginx/1.25.3") == (1, 25, 3)
    assert parse_version("nginx version: nginx/1.24.0 (Ubuntu)") == (1, 24, 0)
    assert parse_version("garbage") is None


def test_system_resolvers(tmp_path: Path) -> None:
    f = tmp_path / "resolv.conf"
    f.write_text(
        "# comment\nnameserver 127.0.0.53\nnameserver fe80::1%eth0\nnameserver bogus\n"
        "search example.com\n"
    )
    assert system_resolvers(f) == ["127.0.0.53", "[fe80::1]"]
    assert system_resolvers(tmp_path / "missing") == []


def test_nginx_missing_binary(tmp_path: Path) -> None:
    n = Nginx("/nonexistent/nginx", tmp_path)
    assert n.version() is None
    with pytest.raises(MissingToolError):
        n.test()


@needs_nginx
def test_nginx_version_probe(tmp_path: Path) -> None:
    n = Nginx(NGINX_BIN, tmp_path)
    ver = n.version()
    assert ver is not None and ver >= (1, 0, 0)
    assert n.version() is ver  # cached
    assert n._base_args()[0] == "-p"
    assert Nginx(NGINX_BIN)._base_args() == []


# -------------------------------------------------------------------- certbot
def test_certbot_build_command() -> None:
    cmd = certbot.build_command(
        "a.example.com", "ops@example.com", True, "certbot", ["www.a.example.com"]
    )
    assert cmd == [
        "certbot",
        "certonly",
        "--nginx",
        "--non-interactive",
        "--agree-tos",
        "-d",
        "a.example.com",
        "-d",
        "www.a.example.com",
        "--email",
        "ops@example.com",
        "--staging",
    ]
    assert "--register-unsafely-without-email" in certbot.build_command("a.example.com")
    with pytest.raises(MissingToolError):
        certbot.require("/nonexistent/certbot")


# --------------------------------------------------------------------- doctor
class FakeNginx(Nginx):
    def __init__(self, ok: bool = True) -> None:
        super().__init__("/nonexistent/nginx", Path("/x"))
        self.ok = ok

    def path(self) -> str | None:
        return "/fake/nginx"

    def version(self) -> tuple[int, int, int] | None:
        return (1, 16, 0)

    def test(self) -> CommandResult:
        return CommandResult(self.ok, "line1\nnginx: test is successful", ["nginx", "-t"])


def test_doctor_reports(manager: Manager) -> None:
    paths = manager.paths
    fake = Manager(paths, FakeNginx(), reload=False)
    (paths.sites_enabled / "dangling.conf").symlink_to(paths.sites_available / "gone.conf")
    (paths.sites_enabled / "plain.conf").write_text("server { listen 8090; }\n")
    (paths.sites_available / "notenabled.conf").write_text("server { listen 8091; }\n")
    (paths.log_dir / "orphan").mkdir()
    (paths.root / "nginx.conf").write_text("events {} http {}\n")
    checks = doctor.run_checks(fake, certbot_bin="/nonexistent/certbot")
    labels = {(c.status, c.label) for c in checks}
    assert (doctor.WARN, "nginx version") in labels
    assert (doctor.FAIL, "broken symlink") in labels
    assert (doctor.WARN, "regular file in sites-enabled") in labels
    assert (doctor.WARN, "available but not enabled") in labels
    assert (doctor.WARN, "orphan log dir") in labels
    assert (doctor.WARN, "certbot") in labels
    assert sum(1 for c in checks if c.label == "nginx.conf" and c.status == doctor.WARN) == 2
    assert doctor.worst(checks) == doctor.FAIL
    assert doctor.worst([doctor.Check(doctor.OK, "x")]) == doctor.OK
    assert doctor.worst([doctor.Check(doctor.WARN, "x")]) == doctor.WARN


def test_doctor_missing_layout(tmp_path: Path) -> None:
    from nginx_manager.fs import Paths

    m = Manager(Paths.build(root=tmp_path / "nowhere"), Nginx("/nonexistent/nginx", tmp_path))
    checks = doctor.run_checks(m, certbot_bin="/nonexistent/certbot")
    assert (doctor.FAIL, "nginx binary") in {(c.status, c.label) for c in checks}
    assert any(c.label == "nginx.conf" and c.status == doctor.FAIL for c in checks)


@pytest.mark.skipif(not HAS_OPENSSL, reason="openssl not available")
def test_doctor_certificate_expiry(manager: Manager, selfsigned: tuple[Path, Path]) -> None:
    cert, key = selfsigned
    fake = Manager(manager.paths, FakeNginx(), reload=False)
    spec = SiteSpec(
        domain="app.example.com",
        proxy_url="http://127.0.0.1:1",
        ssl=True,
        cert=str(cert),
        key=str(key),
    ).validate()
    manager.paths.ensure_dirs()
    manager.paths.available(spec.name).write_text(manager.render(spec))
    # An unmanaged TLS site whose certificate is missing, and one that is unreadable
    (manager.paths.sites_available / "other.example.com.conf").write_text(
        "server { listen 8443 ssl; ssl_certificate /nope.pem; }\n"
    )
    unreadable = manager.paths.letsencrypt_dir / "live" / "bad.example.com"
    unreadable.mkdir(parents=True)
    (unreadable / "fullchain.pem").write_text("not a cert\n")
    (manager.paths.sites_available / "bad.example.com.conf").write_text(
        f"server {{ listen 8444 ssl; ssl_certificate {unreadable}/fullchain.pem; }}\n"
    )
    # Regression: a hand-written TLS site with a certificate outside letsencrypt must be
    # checked at the path its ssl_certificate directive gives, not at a guessed LE path.
    (manager.paths.sites_available / "hand.example.com.conf").write_text(
        "server {\n    listen 8445 ssl;\n    server_name hand.example.com;\n"
        f"    ssl_certificate {cert};\n    ssl_certificate_key {key};\n}}\n"
    )
    # Relative paths are resolved against the nginx prefix, like nginx does.
    (manager.paths.root / "rel.pem").write_bytes(cert.read_bytes())
    (manager.paths.sites_available / "rel.example.com.conf").write_text(
        "server { listen 8446 ssl; ssl_certificate rel.pem; }\n"
    )
    # TLS enabled but the certificate comes from an include or the http context.
    (manager.paths.sites_available / "inc.example.com.conf").write_text(
        "server { listen 8447 ssl; include /etc/nginx/snippets/tls.conf; }\n"
    )
    checks = {c.label: c for c in doctor.run_checks(fake)}
    assert checks["certificate app.example.com"].status == doctor.OK
    assert "expires" in checks["certificate app.example.com"].detail
    assert checks["certificate other.example.com"].status == doctor.FAIL
    assert checks["certificate bad.example.com"].status == doctor.WARN
    assert checks["certificate hand.example.com"].status == doctor.OK
    assert checks["certificate rel.example.com"].status == doctor.OK
    assert checks["certificate inc.example.com"].status == doctor.WARN
    assert "no ssl_certificate directive" in checks["certificate inc.example.com"].detail
    assert "letsencrypt" not in checks["certificate hand.example.com"].detail
    # expired
    far = datetime(2099, 1, 1, tzinfo=timezone.utc)
    checks = {c.label: c for c in doctor.run_checks(fake, now=far)}
    assert checks["certificate app.example.com"].status == doctor.FAIL
    assert doctor.certificate_expiry(unreadable / "fullchain.pem") is None
