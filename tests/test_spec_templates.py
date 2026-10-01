"""Unit tests for SiteSpec validation and template rendering (golden files)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nginx_manager import templates
from nginx_manager.errors import ValidationError
from nginx_manager.spec import Location, SiteSpec
from nginx_manager.templates import RenderContext

GOLDEN = Path(__file__).parent / "golden"


def proxy_spec(**kw: object) -> SiteSpec:
    base: dict[str, object] = {"domain": "app.example.com", "proxy_url": "http://127.0.0.1:3000"}
    base.update(kw)
    return SiteSpec(**base)  # type: ignore[arg-type]


# ----------------------------------------------------------------------- spec
def test_spec_validate_normalises() -> None:
    s = proxy_spec(domain="APP.Example.com", aliases=["WWW.example.com"], port="8080")
    s.validate()
    assert s.domain == "app.example.com"
    assert s.aliases == ["www.example.com"]
    assert s.port == 8080
    assert s.name == "app.example.com"
    assert s.zone == "nm_app_example_com"
    assert s.server_names == ["app.example.com", "www.example.com"]


def test_spec_wildcard_name() -> None:
    s = proxy_spec(domain="*.example.com").validate()
    assert s.name == "_wildcard.example.com"
    assert s.zone == "nm__wildcard_example_com"


@pytest.mark.parametrize(
    "kw",
    [
        {"mode": "weird"},
        {"proxy_url": None},
        {"mode": "static", "proxy_url": None, "root": None},
        {"mode": "static", "proxy_url": None, "root": "relative"},
        {"ssl": True, "port": 443},
        {"redirect_http": True},
        {"hsts": True},
        {"cert": "/a.pem"},
        {"ssl": True, "cert": "/a.pem"},
        {"rate_limit": "fast"},
        {"rate_limit": "1r/s", "rate_burst": 0},
        {"csp": 'bad"'},
        {"resolvers": ["dns.google"]},
        {"locations": [Location("/", [("a", "b")])]},
        {"locations": [Location("/x", [])]},
        {"locations": [Location("/x", [("a", "b")]), Location("/x", [("a", "b")])]},
        {"locations": [Location("/x", [("include", "/etc/passwd")])]},
    ],
)
def test_spec_rejects(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        proxy_spec(**kw).validate()


def test_spec_json_roundtrip() -> None:
    s = proxy_spec(
        ssl=True,
        hsts=True,
        cert="/c.pem",
        key="/k.pem",
        rate_limit="5r/s",
        locations=[Location("/api", [("proxy_pass", "http://127.0.0.1:1"), ("gzip", "on")])],
    ).validate()
    again = SiteSpec.from_json(s.to_json())
    assert again == s
    assert json.loads(s.to_json())["locations"][0]["path"] == "/api"


# ------------------------------------------------------------------ templates
def _check_golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text)
    assert text == path.read_text(), f"golden mismatch for {name} (UPDATE_GOLDEN=1 to refresh)"


def test_golden_proxy(fixed_ctx: RenderContext) -> None:
    _check_golden("proxy.conf", templates.render_site(proxy_spec().validate(), fixed_ctx))


def test_golden_proxy_ssl_full(fixed_ctx: RenderContext) -> None:
    spec = proxy_spec(
        aliases=["www.example.com"],
        ssl=True,
        redirect_http=True,
        hsts=True,
        ipv6=True,
        rate_limit="10r/s",
        csp="default-src 'self'",
        locations=[
            Location(
                "/api",
                [("proxy_pass", "http://127.0.0.1:4000"), ("proxy_set_header", "Host $host")],
            )
        ],
    ).validate()
    _check_golden("proxy_ssl_full.conf", templates.render_site(spec, fixed_ctx))
    _check_golden("proxy_ssl_full.headers.conf", templates.render_headers_snippet(spec, fixed_ctx))
    _check_golden(
        "conf_d.conf", templates.render_conf_d({spec.name: templates.zone_line(spec)}, fixed_ctx)
    )


def test_golden_static(fixed_ctx: RenderContext) -> None:
    spec = SiteSpec(
        domain="www.example.org",
        mode="static",
        root="/var/www/example",
        index="index.html index.htm",
    ).validate()
    _check_golden("static.conf", templates.render_site(spec, fixed_ctx))


def test_http2_directive_depends_on_version(fixed_ctx: RenderContext) -> None:
    spec = proxy_spec(ssl=True).validate()
    legacy = templates.render_site(spec, fixed_ctx)
    assert "listen 443 ssl http2;" in legacy and "http2 on;" not in legacy
    fixed_ctx.nginx_version = (1, 25, 1)
    modern = templates.render_site(spec, fixed_ctx)
    assert "listen 443 ssl;" in modern and "http2 on;" in modern
    fixed_ctx.nginx_version = None
    assert "listen 443 ssl http2;" in templates.render_site(spec, fixed_ctx)


def test_ssl_options_and_resolvers(fixed_ctx: RenderContext) -> None:
    fixed_ctx.ssl_options_file = "/etc/letsencrypt/options-ssl-nginx.conf"
    fixed_ctx.ssl_dhparam_file = "/etc/letsencrypt/ssl-dhparams.pem"
    out = templates.render_site(
        proxy_spec(ssl=True, resolvers=["1.1.1.1", "::1"]).validate(), fixed_ctx
    )
    assert "include /etc/letsencrypt/options-ssl-nginx.conf;" in out
    assert "ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;" in out
    assert "ssl_ciphers" not in out
    assert "resolver 1.1.1.1 [::1] valid=300s;" in out
    fixed_ctx.system_resolvers = []
    out = templates.render_site(proxy_spec(ssl=True).validate(), fixed_ctx)
    assert "ssl_stapling on" not in out and "OCSP stapling disabled" in out


def test_no_websocket_and_no_obsolete_headers(fixed_ctx: RenderContext) -> None:
    out = templates.render_site(proxy_spec(websocket=False).validate(), fixed_ctx)
    assert "$connection_upgrade" not in out and 'proxy_set_header Connection "";' in out
    snippet = templates.render_headers_snippet(proxy_spec().validate(), fixed_ctx)
    assert "X-XSS-Protection" not in snippet
    assert "Content-Security-Policy" not in snippet
    assert "Strict-Transport-Security" not in snippet
    assert "log_format" not in out and "limit_req" not in out
