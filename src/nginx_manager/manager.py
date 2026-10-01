"""High-level operations on sites. Used by both the CLI subcommands and the interactive menu."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import templates
from .errors import NginxTestError, NotFoundError, ValidationError
from .fs import Paths, Transaction
from .nginx import Nginx, system_resolvers
from .spec import SiteSpec
from .templates import MANAGED_MARKER, SPEC_MARKER, RenderContext
from .validators import site_name

Logger = Callable[[str], None]


@dataclass
class SiteInfo:
    name: str
    server_names: list[str]
    ports: list[str]
    kind: str  # proxy | static | other
    ssl: bool
    enabled: bool
    managed: bool
    cert_file: str | None = None  # first ssl_certificate directive, as written

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class Manager:
    def __init__(
        self,
        paths: Paths,
        nginx: Nginx,
        reload: bool = True,
        log: Logger | None = None,
    ) -> None:
        self.paths = paths
        self.nginx = nginx
        self.reload_enabled = reload
        self.log: Logger = log or (lambda _msg: None)

    # ------------------------------------------------------------------ context
    def render_context(self) -> RenderContext:
        le = self.paths.letsencrypt_dir
        opts = le / "options-ssl-nginx.conf"
        dh = le / "ssl-dhparams.pem"
        return RenderContext(
            nginx_version=self.nginx.version(),
            system_resolvers=system_resolvers(),
            headers_snippet_dir=str(self.paths.snippets),
            log_dir=str(self.paths.log_dir),
            letsencrypt_dir=str(le),
            ssl_options_file=str(opts) if opts.is_file() else None,
            ssl_dhparam_file=str(dh) if dh.is_file() else None,
        )

    # ------------------------------------------------------------------ read
    def list_sites(self) -> list[SiteInfo]:
        avail = self.paths.sites_available
        if not avail.is_dir():
            return []
        out = []
        for conf in sorted(p for p in avail.iterdir() if p.is_file()):
            name = conf.name[:-5] if conf.name.endswith(".conf") else conf.name
            out.append(parse_site(name, conf.read_text(errors="replace"), self._is_enabled(conf)))
        return out

    def _is_enabled(self, conf: Path) -> bool:
        link = self.paths.sites_enabled / conf.name
        return link.exists() and link.resolve() == conf.resolve()

    def site_path(self, name: str) -> Path:
        name = site_name(name)
        for candidate in (self.paths.available(name), self.paths.sites_available / name):
            if candidate.is_file():
                return candidate
        raise NotFoundError(f"no site named {name!r} in {self.paths.sites_available}")

    def read_site(self, name: str) -> str:
        return self.site_path(name).read_text(errors="replace")

    def load_spec(self, name: str) -> SiteSpec | None:
        for line in self.read_site(name).splitlines():
            if line.startswith(SPEC_MARKER):
                return SiteSpec.from_json(line[len(SPEC_MARKER) :])
        return None

    # ------------------------------------------------------------------ render
    def render(self, spec: SiteSpec) -> str:
        return templates.render_site(spec, self.render_context())

    def preflight(self, spec: SiteSpec) -> list[str]:
        """Return warnings about things nginx -t would reject, before touching the disk."""
        warnings = []
        if spec.ssl:
            ctx = self.render_context()
            cert = Path(spec.cert or f"{ctx.letsencrypt_dir}/live/{spec.domain}/fullchain.pem")
            key = Path(spec.key or f"{ctx.letsencrypt_dir}/live/{spec.domain}/privkey.pem")
            for p in (cert, key):
                if not p.exists():
                    warnings.append(
                        f"certificate file missing: {p} (run 'nginx-manager cert {spec.domain}'"
                        " first, or use --certbot / --cert and --key)"
                    )
        if spec.mode == "static" and spec.root and not Path(spec.root).is_dir():
            warnings.append(f"static root does not exist: {spec.root}")
        return warnings

    # ------------------------------------------------------------------ write
    def create(self, spec: SiteSpec, force: bool = False, enable: bool = True) -> Path:
        """Write the site (and its snippet/zone), enable it, run nginx -t, reload.

        Any previous version is backed up; on test failure everything is rolled back.
        """
        spec.validate()
        self.paths.ensure_dirs()
        dest = self.paths.available(spec.name)
        if dest.exists() and not force:
            raise ValidationError(f"{dest} already exists (use --force to replace it)")
        missing_cert = [w for w in self.preflight(spec) if "certificate" in w]
        if missing_cert:
            raise NotFoundError(missing_cert[0])

        ctx = self.render_context()
        tx = Transaction(self.paths.backups)
        tx.mkdir(self.paths.site_log_dir(spec.name))
        tx.write(self.paths.snippet(spec.name), templates.render_headers_snippet(spec, ctx))
        zones = self._zones()
        if spec.rate_limit:
            zones[spec.name] = templates.zone_line(spec)
        else:
            zones.pop(spec.name, None)
        tx.write(self.paths.managed_conf, templates.render_conf_d(zones, ctx))
        tx.write(dest, templates.render_site(spec, ctx))
        self.log(f"written {dest}")
        if enable:
            tx.symlink(self.paths.enabled(spec.name), dest)
            self.log(f"enabled {self.paths.enabled(spec.name)}")
        self._commit(tx)
        return dest

    def enable(self, name: str) -> None:
        conf = self.site_path(name)
        link = self.paths.sites_enabled / conf.name
        if self._is_enabled(conf):
            self.log(f"{conf.name} is already enabled")
            return
        self.paths.ensure_dirs()
        tx = Transaction(self.paths.backups)
        tx.symlink(link, conf)
        self.log(f"enabled {link}")
        self._commit(tx)

    def disable(self, name: str) -> None:
        conf = self.site_path(name)
        link = self.paths.sites_enabled / conf.name
        if not link.exists() and not link.is_symlink():
            self.log(f"{conf.name} is already disabled")
            return
        tx = Transaction(self.paths.backups)
        tx.remove(link)
        self.log(f"disabled {link}")
        self._commit(tx)

    def delete(self, name: str, keep_logs: bool = False) -> None:
        conf = self.site_path(name)
        site = conf.name[:-5] if conf.name.endswith(".conf") else conf.name
        tx = Transaction(self.paths.backups)
        tx.remove(self.paths.sites_enabled / conf.name)
        tx.remove(self.paths.snippet(site))
        zones = self._zones()
        if zones.pop(site, None) is not None or self.paths.managed_conf.exists():
            tx.write(self.paths.managed_conf, templates.render_conf_d(zones, self.render_context()))
        tx.remove(conf)
        self.log(f"removed {conf} (backup in {self.paths.backups})")
        self._commit(tx)
        log_dir = self.paths.site_log_dir(site)
        if not keep_logs and log_dir.is_dir():
            shutil.rmtree(log_dir)
            self.log(f"removed logs {log_dir}")

    # ------------------------------------------------------------------ nginx
    def test(self) -> str:
        res = self.nginx.test()
        if not res.ok:
            raise NginxTestError(f"nginx -t failed:\n{res.output}")
        return res.output

    def reload(self) -> str:
        res = self.nginx.reload()
        if not res.ok:
            raise NginxTestError(f"nginx reload failed:\n{res.output}")
        return res.output

    def _commit(self, tx: Transaction) -> None:
        res = self.nginx.test()
        if not res.ok:
            tx.rollback()
            raise NginxTestError(f"nginx -t failed, changes rolled back:\n{res.output}")
        self.log("nginx -t: ok")
        if self.reload_enabled:
            self.reload()
            self.log("nginx reloaded")
        else:
            self.log("reload skipped (--no-reload)")

    # ------------------------------------------------------------------ zones
    def _zones(self) -> dict[str, str]:
        zones: dict[str, str] = {}
        if self.paths.managed_conf.is_file():
            for line in self.paths.managed_conf.read_text().splitlines():
                m = re.match(r"^(limit_req_zone .*;)\s*# site: (\S+)$", line.strip())
                if m:
                    zones[m.group(2)] = m.group(1)
        return zones


# ---------------------------------------------------------------------- parsing
_D = r"(?:^|[{;])\s*"  # a directive starts a line or follows { or ;


def _strip_comments(content: str) -> str:
    return re.sub(r"#.*$", "", content, flags=re.M)


def parse_site(name: str, content: str, enabled: bool) -> SiteInfo:
    managed = content.startswith(MANAGED_MARKER)
    content = _strip_comments(content)
    names: list[str] = []
    for m in re.finditer(_D + r"server_name\s+([^;]+);", content, re.M):
        for n in m.group(1).split():
            if n not in names:
                names.append(n)
    ports: list[str] = []
    for m in re.finditer(_D + r"listen\s+([^;]+);", content, re.M):
        token = m.group(1).split()[0]
        p = token.rsplit(":", 1)[-1]
        if p not in ports:
            ports.append(p)
    if re.search(_D + r"proxy_pass\s", content, re.M):
        kind = "proxy"
    elif re.search(_D + r"root\s", content, re.M):
        kind = "static"
    else:
        kind = "other"
    cert_m = re.search(_D + r"ssl_certificate\s+([^;\s]+)\s*;", content, re.M)
    ssl = cert_m is not None or bool(re.search(_D + r"listen\s[^;]*\bssl\b", content, re.M))
    return SiteInfo(
        name, names, ports, kind, ssl, enabled, managed, cert_m.group(1) if cert_m else None
    )


def explain(content: str) -> list[str]:
    """Human-readable summary of what a config does, derived from the text itself."""
    info = parse_site("-", content, False)
    content = _strip_comments(content)
    lines = [f"server names : {' '.join(info.server_names) or '(none)'}"]
    lines.append(f"listens on   : {', '.join(info.ports) or '(none)'}")
    lines.append(f"kind         : {info.kind}")
    for m in re.finditer(_D + r"proxy_pass\s+([^;]+);", content, re.M):
        lines.append(f"upstream     : {m.group(1)}")
    for m in re.finditer(_D + r"root\s+([^;]+);", content, re.M):
        lines.append(f"document root: {m.group(1)}")
    lines.append(f"tls          : {'yes' if info.ssl else 'no'}")
    if re.search(r"return 301 https://", content):
        lines.append("http         : redirected to https")
    if "http2" in content:
        lines.append("http2        : enabled")
    if "Strict-Transport-Security" in content:
        lines.append("hsts         : enabled (header in snippet)")
    rl = re.search(r"limit_req zone=(\S+) burst=(\d+)", content)
    if rl:
        lines.append(f"rate limit   : zone {rl.group(1)}, burst {rl.group(2)} (429 when exceeded)")
    if "$connection_upgrade" in content:
        lines.append("websocket    : passthrough enabled")
    locs = re.findall(_D + r"location\s+([^{]+?)\s*\{", content, re.M)
    if locs:
        lines.append("locations    : " + ", ".join(locs))
    incs = re.findall(_D + r"include\s+([^;]+);", content, re.M)
    if incs:
        lines.append("includes     : " + ", ".join(sorted(set(incs))))
    lines.append(f"managed      : {'yes (nginx-manager header present)' if info.managed else 'no'}")
    return lines
