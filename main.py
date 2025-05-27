#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SITES_ENABLED   = Path("/etc/nginx/sites-enabled")

# Default proxy headers
DEFAULT_PROXY_HEADERS = [
    ("proxy_set_header", "Host $host"),
    ("proxy_set_header", "X-Real-IP $remote_addr"),
    ("proxy_set_header", "X-Forwarded-For $proxy_add_x_forwarded_for"),
    ("proxy_set_header", "X-Forwarded-Proto $scheme"),
    ("proxy_set_header", "Upgrade $http_upgrade"),
    ("proxy_set_header", "Connection \"upgrade\""),
    ("proxy_redirect", "off"),
    ("proxy_http_version", "1.1"),
]

CERTBOT_SSL_BLOCK = [
    ("listen", "443 ssl"),
    ("ssl_certificate", "/etc/letsencrypt/live/{domain}/fullchain.pem"),
    ("ssl_certificate_key", "/etc/letsencrypt/live/{domain}/privkey.pem"),
    ("include", "/etc/letsencrypt/options-ssl-nginx.conf"),
    ("ssl_dhparam", "/etc/letsencrypt/ssl-dhparams.pem"),
]

REDIRECT_BLOCK = [
    (None, f"if ($host = {{domain}}) {{ return 301 https://$host$request_uri; }}"),
]


def require_root():
    if os.geteuid() != 0:
        print("🚨 This script must be run as root (e.g. sudo).")
        sys.exit(1)


def list_configs():
    print("\n--- Existing Nginx Configs ---")
    confs = sorted(SITES_AVAILABLE.glob("*.conf"))
    if not confs:
        print("  (no .conf files found)")
    else:
        for c in confs:
            print("  •", c.name)
    print()


def prompt(text, default=None):
    if default is None:
        return input(f"{text}: ").strip()
    else:
        resp = input(f"{text} [{default}]: ").strip()
        return resp if resp else default


def confirm(text, default=False):
    yes = {"y","yes"}
    no  = {"n","no"}
    default_str = "Y/n" if default else "y/N"
    while True:
        resp = input(f"{text} ({default_str}): ").strip().lower()
        if not resp:
            return default
        if resp in yes:
            return True
        if resp in no:
            return False
        print("  Please answer yes or no.")


def build_server_block(domain, cfg, locations, ssl=False, redirect=False):
    lines = []
    # Redirect block
    if redirect:
        lines.append(f"server {{")
        lines.append(f"    if ($host = {domain}) {{ return 301 https://$host$request_uri; }} # managed by Certbot")
        lines.append(f"    listen 80;")
        lines.append(f"    server_name {domain};")
        lines.append(f"    return 404; # managed by Certbot")
        lines.append("}")
        return "\n".join(lines)

    # Main server block
    lines.append("server {")
    lines.append(f"    server_name {domain};")
    lines.append(f"    listen {cfg['listen']};")
    # SSL part
    if ssl:
        for directive, tpl in CERTBOT_SSL_BLOCK:
            value = tpl.format(domain=domain)
            lines.append(f"    {directive} {value}; # managed by Certbot")
    # Root or proxy
    if cfg['mode'] == 'proxy':
        lines.append(f"    location {cfg['path']} {{")
        lines.append(f"        proxy_pass {cfg['proxy_pass']};")
        for directive, value in DEFAULT_PROXY_HEADERS:
            lines.append(f"        {directive} {value};")
        lines.append("    }")
    else:
        lines.append(f"    root {cfg['root']};")
        lines.append(f"    index {cfg['index']};")
    # Additional location blocks
    for loc in locations:
        lines.append(f"    location {loc['path']} {{")
        for directive, value in loc['directives']:
            lines.append(f"        {directive} {value};")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def create_config():
    print("\n=== Create a New Nginx Config ===")
    domain = prompt("Enter primary domain (e.g. example.com)")
    cfg = {}
    cfg['listen'] = prompt("Enter listening port", "80")
    # Choose mode: static or proxy
    mode = prompt("Mode? 1=proxy, 2=static (serve files)", "1")
    if mode == '1':
        cfg['mode'] = 'proxy'
        cfg['path'] = prompt("Enter proxy path", "/")
        cfg['proxy_pass'] = prompt("Enter proxy upstream (e.g. http://localhost:5173)")
    else:
        cfg['mode'] = 'static'
        cfg['root'] = prompt("Enter site root directory", "/var/www/html")
        cfg['index'] = prompt("Enter index file(s)", "index.html")

    # Additional custom location blocks
    locations = []
    while confirm("Add additional location block?", default=False):
        path = prompt("  Location path", "/api")
        directives = []
        while True:
            d = prompt("    Directive name (blank to finish)")
            if not d:
                break
            v = prompt(f"    Value for {d}")
            directives.append((d, v))
        locations.append({"path": path, "directives": directives})
        print()

    use_ssl = confirm("Enable SSL block with Certbot placeholders?", default=True)
    add_redirect = False
    if use_ssl:
        add_redirect = confirm("Also generate HTTP->HTTPS redirect block?", default=True)

    # Build blocks
    server_conf = build_server_block(domain, cfg, locations, ssl=use_ssl, redirect=False)
    blocks = [server_conf]
    if add_redirect:
        blocks.insert(0, build_server_block(domain, cfg, locations, ssl=False, redirect=True))

    full_conf = "\n\n".join(blocks)
    print("\n--- Preview of Generated Config ---\n")
    print(full_conf)
    print()

    if not confirm("Write config and enable?", default=False):
        print("Canceled. No files written.\n")
        return

    dest = SITES_AVAILABLE / f"{domain}.conf"
    dest.write_text(full_conf + "\n")
    print(f"[+] Written: {dest}")

    link = SITES_ENABLED / dest.name
    if not link.exists():
        link.symlink_to(dest)
        print(f"[+] Enabled: {link}")

    print("\nTesting nginx syntax...")
    subprocess.run(["nginx", "-t"], check=True)
    print("Reloading nginx...")
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("✅ Configuration applied!\n")


def main():
    require_root()
    while True:
        print("=== Nginx Interactive Manager ===")
        print("1) List existing configs")
        print("2) Create a new config")
        print("3) Quit")
        choice = prompt("Choose an action", "3")
        if choice == "1":
            list_configs()
        elif choice == "2":
            create_config()
        else:
            print("Goodbye!")
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
    except subprocess.CalledProcessError:
        print("❌ Nginx reported an error. Please check your config.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)
