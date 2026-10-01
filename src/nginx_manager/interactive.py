"""Interactive menu. Thin layer of prompts over the same functions the subcommands use."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from . import ui
from .cli import App, cmd_doctor, cmd_list, do_create
from .errors import NginxManagerError, ValidationError
from .spec import Location, SiteSpec

Prompt = Callable[[str], str]


def ask(text: str, default: str | None = None, prompt: Prompt = input) -> str:
    suffix = f" [{default}]" if default is not None else ""
    answer = prompt(f"{text}{suffix}: ").strip()
    return answer or (default or "")


def ask_until_valid(
    text: str, validate: Callable[[str], object], default: str | None = None, prompt: Prompt = input
) -> str:
    while True:
        value = ask(text, default, prompt)
        try:
            validate(value)
            return value
        except ValidationError as exc:
            print(f"  {exc}")


def yes_no(text: str, default: bool, prompt: Prompt = input) -> bool:
    answer = ask(text, "Y/n" if default else "y/N", prompt).lower()
    if answer in ("y/n", ""):
        return default
    return answer in ("y", "yes")


def build_spec(prompt: Prompt = input) -> SiteSpec:
    from . import validators as v

    print("\n== create a site ==")
    domain = ask_until_valid("domain", v.domain, prompt=prompt)
    aliases = ask("extra server names (space separated)", "", prompt).split()
    port = ask_until_valid("HTTP port", v.port, "80", prompt)
    mode = ask("mode: 1=reverse proxy, 2=static files", "1", prompt)
    spec = SiteSpec(domain=domain, aliases=aliases, port=int(port))
    if mode == "2":
        spec.mode = "static"
        spec.root = ask_until_valid("root directory", v.absolute_path, "/var/www/html", prompt)
        spec.index = ask_until_valid("index files", v.index_files, "index.html", prompt)
    else:
        spec.proxy_url = ask_until_valid(
            "upstream URL", v.upstream, "http://127.0.0.1:3000", prompt
        )
        spec.proxy_path = ask_until_valid("location path", v.url_path, "/", prompt)
        spec.websocket = yes_no("pass WebSocket upgrades?", True, prompt)
    while yes_no("add a custom location block?", False, prompt):
        path = ask_until_valid("  location path", v.url_path, "/api", prompt)
        loc = Location(path)
        while True:
            name = ask("    directive name (blank to finish)", "", prompt)
            if not name:
                break
            try:
                value = ask(f"    value for {name}", None, prompt)
                loc.directives.append((v.directive_name(name), v.directive_value(value)))
            except ValidationError as exc:
                print(f"  {exc}")
        if loc.directives:
            spec.locations.append(loc)
    spec.ssl = yes_no(
        "enable TLS (certificate must already exist, or use certbot next)?", False, prompt
    )
    if spec.ssl:
        spec.redirect_http = yes_no("redirect HTTP to HTTPS?", True, prompt)
        spec.hsts = yes_no("send HSTS header (2 years, no preload)?", False, prompt)
    if yes_no("enable rate limiting?", False, prompt):
        spec.rate_limit = ask_until_valid("rate (e.g. 10r/s)", v.rate, "10r/s", prompt)
    csp = ask("Content-Security-Policy (blank for none)", "", prompt)
    spec.csp = csp or None
    return spec


MENU = """
nginx-manager {version} - {root}
 1) list sites            5) delete a site
 2) create a site         6) run nginx -t (and reload)
 3) show a site           7) doctor
 4) enable / disable      q) quit
"""


def run_menu(app: App, prompt: Prompt = input) -> int:
    from . import __version__

    while True:
        print(MENU.format(version=__version__, root=app.paths.root))
        choice = ask("choice", "q", prompt).lower()
        try:
            if choice == "1":
                cmd_list(app, argparse.Namespace(json=False))
            elif choice == "2":
                spec = build_spec(prompt)
                use_certbot = not spec.ssl and yes_no(
                    "obtain a Let's Encrypt certificate with certbot and enable TLS?", False, prompt
                )
                email = ask("account email", "", prompt) if use_certbot else None
                if use_certbot:
                    spec.ssl, spec.redirect_http = True, True
                force = app.paths.available(spec.name).exists() and yes_no(
                    f"{spec.name}.conf exists, replace it (backup kept)?", False, prompt
                )
                do_create(
                    app, spec, yes=False, force=force, use_certbot=use_certbot, email=email or None
                )
            elif choice == "3":
                name = ask("site name", None, prompt)
                print(app.manager.read_site(name))
            elif choice == "4":
                name = ask("site name", None, prompt)
                if yes_no("enable (y) or disable (n)?", True, prompt):
                    app.manager.enable(name)
                    ui.ok("enabled")
                else:
                    app.manager.disable(name)
                    ui.ok("disabled")
            elif choice == "5":
                name = ask("site name to delete", None, prompt)
                if yes_no(f"really delete {name}?", False, prompt):
                    app.manager.delete(name, keep_logs=yes_no("keep its logs?", True, prompt))
                    ui.ok("deleted")
            elif choice == "6":
                print(app.manager.test())
                if app.manager.reload_enabled and yes_no("reload nginx?", True, prompt):
                    app.manager.reload()
                    ui.ok("reloaded")
            elif choice == "7":
                cmd_doctor(app, argparse.Namespace())
            elif choice in ("q", "quit", "exit"):
                return 0
            else:
                print("unknown choice")
        except NginxManagerError as exc:
            ui.error(str(exc))
        except SystemExit as exc:  # ui.confirm without a TTY
            ui.error(str(exc))
