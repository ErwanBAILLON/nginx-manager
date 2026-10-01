"""Command-line entry point: argparse subcommands, or the interactive menu with no arguments."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import __version__, certbot, doctor, ui
from . import validators as v
from .errors import NginxManagerError, ValidationError
from .fs import Paths
from .manager import Manager, explain
from .nginx import Nginx
from .spec import Location, SiteSpec


@dataclass
class App:
    paths: Paths
    nginx: Nginx
    manager: Manager
    verbose: bool = False
    certbot_bin: str = "certbot"


# ------------------------------------------------------------------------ parser
def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("global options")
    g.add_argument(
        "--root-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="nginx configuration root (default /etc/nginx)",
    )
    g.add_argument(
        "--log-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="per-site log directory (default /var/log/nginx, or ROOT/log)",
    )
    g.add_argument(
        "--letsencrypt-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="certbot directory (default /etc/letsencrypt, or ROOT/letsencrypt)",
    )
    g.add_argument(
        "--nginx-bin",
        default=argparse.SUPPRESS,
        metavar="BIN",
        help="nginx binary (default: nginx from PATH)",
    )
    g.add_argument("--certbot-bin", default=argparse.SUPPRESS, metavar="BIN")
    g.add_argument(
        "--no-reload",
        action="store_true",
        default=argparse.SUPPRESS,
        help="never run 'nginx -s reload' after a successful change",
    )
    g.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS)
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="nginx-manager",
        description="Generate, validate and manage nginx virtual hosts. "
        "Run without a subcommand for the interactive menu.",
        epilog="exit codes: 0 ok, 1 validation error, 2 usage, 3 nginx -t/reload failed, "
        "4 permission denied, 5 not found, 6 missing tool",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("list", parents=[common], help="list sites in sites-available")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("show", parents=[common], help="print a site's config")
    p.add_argument("name")
    p.add_argument("--explain", action="store_true", help="summarise what the config does")

    p = sub.add_parser("create", parents=[common], help="generate, test and enable a site")
    p.add_argument("domain")
    kind = p.add_mutually_exclusive_group(required=True)
    kind.add_argument("--proxy", metavar="URL", help="reverse proxy to http(s)://host[:port]")
    kind.add_argument("--static", metavar="DIR", help="serve files from an absolute directory")
    p.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="DOMAIN",
        help="extra server_name (repeatable)",
    )
    p.add_argument("--port", type=int, default=80, help="HTTP listen port (default 80)")
    p.add_argument("--ipv6", action="store_true", help="also listen on [::]")
    p.add_argument("--proxy-path", default="/", metavar="PATH", help="location for --proxy")
    p.add_argument("--no-websocket", action="store_true", help="do not pass WebSocket upgrades")
    p.add_argument("--index", default="index.html", help="index files for --static")
    p.add_argument(
        "--location",
        action="append",
        default=[],
        metavar="PATH:DIRECTIVE=VALUE",
        help="extra location directive (repeatable, same PATH groups together)",
    )
    p.add_argument("--ssl", action="store_true", help="add a TLS server (certbot paths by default)")
    p.add_argument("--ssl-port", type=int, default=443)
    p.add_argument("--cert", metavar="PEM", help="certificate chain (default letsencrypt live)")
    p.add_argument("--key", metavar="PEM", help="private key (default letsencrypt live)")
    p.add_argument("--redirect-http", action="store_true", help="301 plain HTTP to HTTPS")
    p.add_argument("--hsts", action="store_true", help="send Strict-Transport-Security (2 years)")
    p.add_argument("--csp", metavar="POLICY", help="Content-Security-Policy value (opt-in)")
    p.add_argument("--rate-limit", metavar="RATE", help="limit_req per IP, e.g. 10r/s")
    p.add_argument("--rate-burst", type=int, default=20)
    p.add_argument(
        "--resolver",
        action="append",
        default=[],
        metavar="IP",
        help="resolver for OCSP stapling (default: /etc/resolv.conf)",
    )
    p.add_argument(
        "--certbot",
        action="store_true",
        help="write HTTP site, obtain a Let's Encrypt cert, then switch to --ssl",
    )
    p.add_argument("--email", help="account email for --certbot")
    p.add_argument("--staging", action="store_true", help="Let's Encrypt staging CA")
    p.add_argument("--force", action="store_true", help="replace an existing site (backup kept)")
    p.add_argument("--no-enable", action="store_true", help="write to sites-available only")
    p.add_argument("--dry-run", action="store_true", help="print the config, write nothing")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")

    for name, help_ in (
        ("enable", "symlink a site into sites-enabled"),
        ("disable", "remove the sites-enabled symlink"),
    ):
        p = sub.add_parser(name, parents=[common], help=help_)
        p.add_argument("name")

    p = sub.add_parser("delete", parents=[common], help="remove a site (backup kept)")
    p.add_argument("name")
    p.add_argument("--yes", "-y", action="store_true")
    p.add_argument("--keep-logs", action="store_true")

    p = sub.add_parser("cert", parents=[common], help="obtain a certificate with certbot")
    p.add_argument("domain")
    p.add_argument("--alias", action="append", default=[], metavar="DOMAIN")
    p.add_argument("--email")
    p.add_argument("--staging", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")

    sub.add_parser("test", parents=[common], help="run nginx -t")
    sub.add_parser("reload", parents=[common], help="run nginx -t then nginx -s reload")
    sub.add_parser("doctor", parents=[common], help="check the installation and managed sites")
    return parser


# --------------------------------------------------------------------------- app
def build_app(ns: argparse.Namespace) -> App:
    paths = Paths.build(
        root=getattr(ns, "root_dir", None),
        log_dir=getattr(ns, "log_dir", None),
        letsencrypt_dir=getattr(ns, "letsencrypt_dir", None),
    )
    verbose = getattr(ns, "verbose", False)
    nginx = Nginx(getattr(ns, "nginx_bin", "nginx"), paths.root)
    manager = Manager(
        paths,
        nginx,
        reload=not getattr(ns, "no_reload", False),
        log=(lambda m: print(ui.paint("  " + m, "dim"))) if verbose else None,
    )
    return App(paths, nginx, manager, verbose, getattr(ns, "certbot_bin", "certbot"))


def spec_from_args(ns: argparse.Namespace) -> SiteSpec:
    locations: dict[str, Location] = {}
    for raw in ns.location:
        path, name, value = v.location_arg(raw)
        locations.setdefault(path, Location(path)).directives.append((name, value))
    return SiteSpec(
        domain=ns.domain,
        mode="proxy" if ns.proxy else "static",
        aliases=list(ns.alias),
        port=ns.port,
        ipv6=ns.ipv6,
        proxy_url=ns.proxy,
        proxy_path=ns.proxy_path,
        websocket=not ns.no_websocket,
        root=ns.static,
        index=ns.index,
        ssl=ns.ssl or ns.certbot,
        ssl_port=ns.ssl_port,
        cert=ns.cert,
        key=ns.key,
        redirect_http=ns.redirect_http,
        hsts=ns.hsts,
        resolvers=list(ns.resolver),
        csp=ns.csp,
        rate_limit=ns.rate_limit,
        rate_burst=ns.rate_burst,
        locations=list(locations.values()),
    )


# ---------------------------------------------------------------------- commands
def cmd_list(app: App, ns: argparse.Namespace) -> int:
    sites = app.manager.list_sites()
    if ns.json:
        print(json.dumps([s.to_dict() for s in sites], indent=2))
        return 0
    if not sites:
        print(f"no sites in {app.paths.sites_available}")
        return 0
    rows = [
        (
            s.name,
            " ".join(s.server_names) or "-",
            ",".join(s.ports) or "-",
            s.kind,
            "yes" if s.ssl else "no",
            "yes" if s.enabled else "no",
            "yes" if s.managed else "no",
        )
        for s in sites
    ]
    print(ui.table(("NAME", "SERVER_NAME", "PORTS", "KIND", "TLS", "ENABLED", "MANAGED"), rows))
    return 0


def cmd_show(app: App, ns: argparse.Namespace) -> int:
    content = app.manager.read_site(ns.name)
    if ns.explain:
        print(f"# {app.manager.site_path(ns.name)}")
        print("\n".join(explain(content)))
    else:
        print(content, end="")
    return 0


def do_create(
    app: App,
    spec: SiteSpec,
    *,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
    enable: bool = True,
    use_certbot: bool = False,
    email: str | None = None,
    staging: bool = False,
) -> int:
    """Shared by the ``create`` subcommand and the interactive menu."""
    spec.validate()
    if use_certbot:
        certbot.require(app.certbot_bin)
        if spec.cert:
            raise ValidationError("--certbot and --cert/--key are mutually exclusive")

    rendered = app.manager.render(spec)
    print(rendered, end="")
    if dry_run:
        print(
            f"# dry-run: nothing written (target {app.paths.available(spec.name)})", file=sys.stderr
        )
        return 0
    for warning in app.manager.preflight(spec):
        if use_certbot and "certificate" in warning:
            continue
        ui.warn(warning)
    if not ui.confirm(f"Write and enable {spec.name}.conf?", default=True, assume_yes=yes):
        print("cancelled, nothing written")
        return 1

    if use_certbot:
        # Step 1: HTTP-only site so certbot can answer the challenge through nginx.
        http_spec = dataclasses.replace(spec, ssl=False, redirect_http=False, hsts=False)
        app.manager.create(http_spec, force=force, enable=True)
        cmd = certbot.build_command(spec.domain, email, staging, app.certbot_bin, spec.aliases)
        print("running: " + " ".join(cmd))
        rc = certbot.run(cmd)
        if rc != 0:
            ui.error(f"certbot exited with {rc}; the HTTP-only site stays enabled")
            return 6
        force = True
    app.manager.create(spec, force=force, enable=enable)
    ui.ok(f"{spec.name}.conf written" + (" and enabled" if enable else ""))
    return 0


def cmd_create(app: App, ns: argparse.Namespace) -> int:
    return do_create(
        app,
        spec_from_args(ns),
        dry_run=ns.dry_run,
        yes=ns.yes,
        force=ns.force,
        enable=not ns.no_enable,
        use_certbot=ns.certbot,
        email=ns.email,
        staging=ns.staging,
    )


def cmd_enable(app: App, ns: argparse.Namespace) -> int:
    app.manager.enable(ns.name)
    ui.ok(f"{ns.name} enabled")
    return 0


def cmd_disable(app: App, ns: argparse.Namespace) -> int:
    app.manager.disable(ns.name)
    ui.ok(f"{ns.name} disabled")
    return 0


def cmd_delete(app: App, ns: argparse.Namespace) -> int:
    path = app.manager.site_path(ns.name)
    if not ui.confirm(f"Delete {path}?", default=False, assume_yes=ns.yes):
        print("cancelled")
        return 1
    app.manager.delete(ns.name, keep_logs=ns.keep_logs)
    ui.ok(f"{ns.name} deleted (backup in {app.paths.backups})")
    return 0


def cmd_cert(app: App, ns: argparse.Namespace) -> int:
    domain = v.domain(ns.domain)
    aliases = [v.domain(a) for a in ns.alias]
    email = v.email(ns.email) if ns.email else None
    certbot.require(app.certbot_bin)
    cmd = certbot.build_command(domain, email, ns.staging, app.certbot_bin, aliases)
    print("will run: " + " ".join(cmd))
    if not email:
        ui.warn("no --email: you will not receive expiry notices from Let's Encrypt")
    if not ui.confirm("Proceed?", default=True, assume_yes=ns.yes):
        print("cancelled")
        return 1
    rc = certbot.run(cmd)
    if rc == 0:
        ui.ok(f"certificate obtained; files in {app.paths.letsencrypt_dir}/live/{domain}/")
        return 0
    ui.error(f"certbot exited with {rc}")
    return 6


def cmd_test(app: App, ns: argparse.Namespace) -> int:
    print(app.manager.test())
    return 0


def cmd_reload(app: App, ns: argparse.Namespace) -> int:
    app.manager.test()
    app.manager.reload()
    ui.ok("nginx reloaded")
    return 0


def cmd_doctor(app: App, ns: argparse.Namespace) -> int:
    checks = doctor.run_checks(app.manager, app.certbot_bin)
    color = {doctor.OK: "green", doctor.WARN: "yellow", doctor.FAIL: "red"}
    for c in checks:
        print(f"{ui.paint(c.status.ljust(4), color[c.status])}  {c.label}: {c.detail}".rstrip())
    worst = doctor.worst(checks)
    print(f"\n{len(checks)} checks, overall: {worst}")
    return 1 if worst == doctor.FAIL else 0


COMMANDS = {
    "list": cmd_list,
    "show": cmd_show,
    "create": cmd_create,
    "enable": cmd_enable,
    "disable": cmd_disable,
    "delete": cmd_delete,
    "cert": cmd_cert,
    "test": cmd_test,
    "reload": cmd_reload,
    "doctor": cmd_doctor,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        app = build_app(ns)
        if ns.command is None:
            from .interactive import run_menu

            return run_menu(app)
        return COMMANDS[ns.command](app, ns)
    except NginxManagerError as exc:
        ui.error(str(exc))
        return exc.exit_code
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
