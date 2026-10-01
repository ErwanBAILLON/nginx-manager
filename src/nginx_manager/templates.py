"""Render nginx configuration text from a validated ``SiteSpec``.

Plain Python, no template engine: every directive is visible here, which makes the
generated output easy to audit. Three artefacts are produced per site:

* the server file (``sites-available/<name>.conf``)
* a headers snippet included in the server block *and* in every location, because an
  ``add_header`` inside a location silently discards the ones inherited from the server
* the shared ``conf.d/nginx-manager.conf`` (http context: websocket map, rate-limit zones)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import __version__
from .errors import ValidationError
from .spec import Location, SiteSpec

SPEC_MARKER = "# nginx-manager-spec: "
MANAGED_MARKER = "# managed by nginx-manager"
STATIC_ASSETS_RE = r"~* \.(?:css|js|mjs|jpe?g|png|gif|ico|svg|webp|avif|woff2?|ttf)$"


@dataclass
class RenderContext:
    """Environment facts needed to render; gathered once by the manager."""

    nginx_version: tuple[int, int, int] | None = None
    system_resolvers: list[str] = field(default_factory=list)
    headers_snippet_dir: str = "/etc/nginx/snippets/nginx-manager"
    log_dir: str = "/var/log/nginx"
    letsencrypt_dir: str = "/etc/letsencrypt"
    ssl_options_file: str | None = None  # /etc/letsencrypt/options-ssl-nginx.conf if present
    ssl_dhparam_file: str | None = None  # /etc/letsencrypt/ssl-dhparams.pem if present
    now: datetime | None = None
    version: str = __version__

    @property
    def http2_directive(self) -> bool:
        """``http2 on;`` exists since nginx 1.25.1; before that it is a ``listen`` flag."""
        return self.nginx_version is not None and self.nginx_version >= (1, 25, 1)

    def timestamp(self) -> str:
        dt = self.now or datetime.now(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def header(ctx: RenderContext) -> str:
    return (
        f"{MANAGED_MARKER} v{ctx.version}, generated {ctx.timestamp()}; "
        "edit at your own risk (re-running create overwrites this file, a backup is kept)"
    )


def headers_snippet_path(spec: SiteSpec, ctx: RenderContext) -> str:
    return f"{ctx.headers_snippet_dir}/{spec.name}.headers.conf"


# --------------------------------------------------------------------------- snippet
def render_headers_snippet(spec: SiteSpec, ctx: RenderContext) -> str:
    lines = [
        header(ctx),
        "# Security headers for " + spec.domain + ". Included in the server block and in",
        "# every location, because add_header in a location drops inherited headers.",
        "add_header X-Content-Type-Options nosniff always;",
        "add_header X-Frame-Options SAMEORIGIN always;",
        "add_header Referrer-Policy strict-origin-when-cross-origin always;",
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
    ]
    if spec.hsts:
        lines.append(
            "# HSTS: browsers will refuse plain HTTP for this host for 2 years. "
            "'preload' is deliberately absent: submitting to the preload list is irreversible."
        )
        lines.append(
            'add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;'
        )
    if spec.csp:
        lines.append(f'add_header Content-Security-Policy "{spec.csp}" always;')
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- conf.d
def render_conf_d(zones: dict[str, str], ctx: RenderContext) -> str:
    """http-context directives shared by all generated sites.

    ``zones`` maps a site name to its ``limit_req_zone`` line (without the trailing tag).
    """
    lines = [
        header(ctx),
        "# http-context directives required by sites generated with nginx-manager.",
        "",
        "# Only send 'Connection: upgrade' to the backend for real WebSocket handshakes.",
        "map $http_upgrade $connection_upgrade {",
        "    default upgrade;",
        "    ''      close;",
        "}",
        "",
        "# Rate-limit zones, one per site that opted in (--rate-limit). Managed automatically.",
    ]
    for name in sorted(zones):
        lines.append(f"{zones[name]}  # site: {name}")
    return "\n".join(lines) + "\n"


def zone_line(spec: SiteSpec) -> str:
    return f"limit_req_zone $binary_remote_addr zone={spec.zone}:10m rate={spec.rate_limit};"


# --------------------------------------------------------------------------- site
def _listen(port: int, ipv6: bool, ssl: bool = False) -> list[str]:
    flag = " ssl" if ssl else ""
    out = [f"listen {port}{flag};"]
    if ipv6:
        out.append(f"listen [::]:{port}{flag};")
    return out


def _ssl_block(spec: SiteSpec, ctx: RenderContext) -> list[str]:
    cert = spec.cert or f"{ctx.letsencrypt_dir}/live/{spec.domain}/fullchain.pem"
    key = spec.key or f"{ctx.letsencrypt_dir}/live/{spec.domain}/privkey.pem"
    lines = [
        "# TLS",
        f"ssl_certificate     {cert};",
        f"ssl_certificate_key {key};",
    ]
    if ctx.ssl_options_file:
        lines.append(f"include {ctx.ssl_options_file};  # certbot's maintained TLS parameters")
    else:
        lines += [
            "ssl_session_timeout 1d;",
            "ssl_session_cache shared:nginx_manager_ssl:10m;",
            "ssl_session_tickets off;",
            "ssl_protocols TLSv1.2 TLSv1.3;",
            "ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
            "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
            "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;",
            "ssl_prefer_server_ciphers off;",
        ]
    if ctx.ssl_dhparam_file:
        lines.append(f"ssl_dhparam {ctx.ssl_dhparam_file};")
    if spec.ocsp_stapling:
        resolvers = spec.resolvers or ctx.system_resolvers
        if not resolvers:
            raise ValidationError(
                "--ocsp-stapling needs a resolver: none found in /etc/resolv.conf, use --resolver"
            )
        lines += [
            "# OCSP stapling (opt-in; resolver from /etc/resolv.conf unless --resolver is given)",
            "ssl_stapling on;",
            "ssl_stapling_verify on;",
            f"resolver {' '.join(resolvers)} valid=300s;",
            "resolver_timeout 5s;",
        ]
    return lines


def _proxy_location(spec: SiteSpec, include: str) -> list[str]:
    lines = [
        f"location {spec.proxy_path} {{",
        f"    proxy_pass {spec.proxy_url};",
        "    proxy_http_version 1.1;",
        "    proxy_set_header Host $host;",
        "    proxy_set_header X-Real-IP $remote_addr;",
        "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "    proxy_set_header X-Forwarded-Proto $scheme;",
        "    proxy_set_header X-Forwarded-Host $host;",
    ]
    if spec.websocket:
        lines += [
            "    # WebSocket passthrough (map in conf.d/nginx-manager.conf)",
            "    proxy_set_header Upgrade $http_upgrade;",
            "    proxy_set_header Connection $connection_upgrade;",
            "    proxy_read_timeout 3600s;",
        ]
    else:
        lines += ['    proxy_set_header Connection "";', "    proxy_read_timeout 60s;"]
    lines += [
        "    proxy_connect_timeout 10s;",
        "    proxy_send_timeout 60s;",
        "    proxy_buffers 16 16k;",
        "    proxy_buffer_size 16k;",
        f"    include {include};",
        "}",
    ]
    return lines


def _static_locations(spec: SiteSpec, include: str) -> list[str]:
    return [
        f"root  {spec.root};",
        f"index {spec.index};",
        "",
        "location / {",
        "    try_files $uri $uri/ =404;",
        f"    include {include};",
        "}",
        "",
        f"location {STATIC_ASSETS_RE} {{",
        "    expires 30d;",
        '    add_header Cache-Control "public, no-transform" always;',
        f"    include {include};",
        "}",
        "",
        "# Deny dotfiles (.git, .env, .htaccess...) except ACME challenges",
        "location ~ /\\.(?!well-known) {",
        "    deny all;",
        "}",
    ]


def _custom_location(loc: Location, include: str) -> list[str]:
    width = max(len(n) for n, _ in loc.directives)
    body = [f"    {n.ljust(width)} {val};" for n, val in loc.directives]
    return [f"location {loc.path} {{", *body, f"    include {include};", "}"]


def _indent(lines: list[str]) -> list[str]:
    return [("    " + line) if line else "" for line in lines]


def render_site(spec: SiteSpec, ctx: RenderContext) -> str:
    include = headers_snippet_path(spec, ctx)
    names = " ".join(spec.server_names)
    log_prefix = f"{ctx.log_dir}/{spec.name}"
    out = [header(ctx), SPEC_MARKER + spec.to_json(), ""]

    if spec.ssl and spec.redirect_http:
        out += [
            "# Plain HTTP: redirect everything to HTTPS",
            "server {",
            *_indent(_listen(spec.port, spec.ipv6)),
            f"    server_name {names};",
            f"    access_log {log_prefix}/access.log;",
            f"    error_log  {log_prefix}/error.log warn;",
            "    return 301 https://$host$request_uri;",
            "}",
            "",
        ]

    body: list[str] = []
    if not (spec.ssl and spec.redirect_http):
        body += _listen(spec.port, spec.ipv6)
    if spec.ssl:
        if ctx.http2_directive:
            body += [*_listen(spec.ssl_port, spec.ipv6, ssl=True), "http2 on;"]
        else:
            body += [line[:-1] + " http2;" for line in _listen(spec.ssl_port, spec.ipv6, ssl=True)]
    body += [
        f"server_name {names};",
        "",
        f"access_log {log_prefix}/access.log;",
        f"error_log  {log_prefix}/error.log warn;",
        "",
        "# Security headers (also included in every location below)",
        f"include {include};",
    ]
    if spec.rate_limit:
        body += [
            "",
            f"# Rate limiting: {spec.rate_limit} per client IP, burst {spec.rate_burst}",
            f"limit_req zone={spec.zone} burst={spec.rate_burst} nodelay;",
            "limit_req_status 429;",
        ]
    if spec.ssl:
        body += ["", *_ssl_block(spec, ctx)]
    body.append("")
    if spec.mode == "proxy":
        body += _proxy_location(spec, include)
    else:
        body += _static_locations(spec, include)
    for loc in spec.locations:
        body += ["", *_custom_location(loc, include)]

    out += ["server {", *_indent(body), "}"]
    return "\n".join(out) + "\n"
