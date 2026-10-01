"""Health checks on the nginx layout and the sites managed by nginx-manager."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .fs import Paths
from .manager import Manager
from .nginx import Nginx

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    status: str
    label: str
    detail: str = ""


def run_checks(
    manager: Manager, certbot_bin: str = "certbot", now: datetime | None = None
) -> list[Check]:
    paths, nginx = manager.paths, manager.nginx
    checks: list[Check] = []

    is_root = os.geteuid() == 0
    checks.append(
        Check(
            OK if is_root else WARN,
            "privileges",
            "running as root" if is_root else "not root: writes to /etc/nginx will fail",
        )
    )
    checks += _nginx_checks(nginx)
    checks += _layout_checks(paths)
    checks += _symlink_checks(paths)
    checks.append(
        Check(
            OK if shutil.which(certbot_bin) else WARN,
            "certbot",
            shutil.which(certbot_bin) or "not installed (optional, needed for 'cert')",
        )
    )
    checks += _certificate_checks(manager, now or datetime.now(timezone.utc))
    checks += _orphan_log_checks(manager)
    return checks


def _nginx_checks(nginx: Nginx) -> list[Check]:
    path = nginx.path()
    if path is None:
        return [Check(FAIL, "nginx binary", f"{nginx.binary!r} not found in PATH")]
    ver = nginx.version()
    ver_s = ".".join(map(str, ver)) if ver else "unknown"
    out = [Check(OK, "nginx binary", f"{path} (version {ver_s})")]
    if ver and ver < (1, 18, 0):
        out.append(Check(WARN, "nginx version", f"{ver_s} is old; TLSv1.3 may be unavailable"))
    res = nginx.test()
    out.append(
        Check(OK if res.ok else FAIL, "nginx -t", res.output.splitlines()[-1] if res.output else "")
    )
    return out


def _layout_checks(paths: Paths) -> list[Check]:
    out = []
    for label, d in (
        ("sites-available", paths.sites_available),
        ("sites-enabled", paths.sites_enabled),
        ("conf.d", paths.conf_d),
        ("log dir", paths.log_dir),
    ):
        out.append(
            Check(OK if d.is_dir() else FAIL, label, str(d) if d.is_dir() else f"missing: {d}")
        )
    nginx_conf = paths.root / "nginx.conf"
    if nginx_conf.is_file():
        text = nginx_conf.read_text(errors="replace")
        for needle, what in (("sites-enabled", "sites-enabled/*"), ("conf.d", "conf.d/*.conf")):
            if needle not in text:
                out.append(Check(WARN, "nginx.conf", f"does not seem to include {what}"))
    else:
        out.append(Check(FAIL, "nginx.conf", f"missing: {nginx_conf}"))
    return out


def _symlink_checks(paths: Paths) -> list[Check]:
    out = []
    if paths.sites_enabled.is_dir():
        for link in sorted(paths.sites_enabled.iterdir()):
            if link.is_symlink() and not link.exists():
                out.append(Check(FAIL, "broken symlink", f"{link} -> {os.readlink(link)}"))
            elif not link.is_symlink():
                out.append(Check(WARN, "regular file in sites-enabled", str(link)))
    if paths.sites_available.is_dir():
        for conf in sorted(paths.sites_available.iterdir()):
            if conf.is_file() and not (paths.sites_enabled / conf.name).exists():
                out.append(Check(WARN, "available but not enabled", conf.name))
    if not out:
        out.append(Check(OK, "sites", "every site in sites-available is enabled, no broken links"))
    return out


def certificate_expiry(cert: Path) -> datetime | None:
    if shutil.which("openssl") is None:
        return None
    proc = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", str(cert)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or "=" not in proc.stdout:
        return None
    raw = proc.stdout.strip().split("=", 1)[1]
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _certificate_checks(manager: Manager, now: datetime) -> list[Check]:
    out = []
    for site in manager.list_sites():
        if not site.ssl:
            continue
        # Use what the config actually says (ssl_certificate directive); a relative path
        # is resolved against the nginx prefix like nginx does. Never guess a Let's
        # Encrypt path for a hand-written site.
        if site.cert_file is None:
            out.append(
                Check(
                    WARN,
                    f"certificate {site.name}",
                    "no ssl_certificate directive in the file (inherited or included?)",
                )
            )
            continue
        cert = Path(site.cert_file)
        if not cert.is_absolute():
            cert = manager.paths.root / cert
        if not cert.exists():
            out.append(Check(FAIL, f"certificate {site.name}", f"missing: {cert}"))
            continue
        exp = certificate_expiry(cert)
        if exp is None:
            out.append(Check(WARN, f"certificate {site.name}", f"cannot read expiry of {cert}"))
            continue
        days = (exp - now).days
        status = FAIL if days < 0 else WARN if days < 14 else OK
        out.append(
            Check(status, f"certificate {site.name}", f"expires {exp:%Y-%m-%d} ({days} days)")
        )
    return out


def _orphan_log_checks(manager: Manager) -> list[Check]:
    log_dir = manager.paths.log_dir
    if not log_dir.is_dir():
        return []
    names = {s.name for s in manager.list_sites()}
    out = [
        Check(WARN, "orphan log dir", str(d))
        for d in sorted(log_dir.iterdir())
        if d.is_dir() and d.name not in names
    ]
    return out


def worst(checks: list[Check]) -> str:
    statuses = {c.status for c in checks}
    return FAIL if FAIL in statuses else WARN if WARN in statuses else OK
