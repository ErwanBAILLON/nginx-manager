#!/usr/bin/env python3
import os
import sys
import subprocess
import re
from pathlib import Path

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SITES_ENABLED   = Path("/etc/nginx/sites-enabled")


class NginxConfigBuilder:
    CERTBOT_SSL_BLOCK = [
        ("listen", "443 ssl"),
        ("ssl_certificate", "/etc/letsencrypt/live/{domain}/fullchain.pem"),
        ("ssl_certificate_key", "/etc/letsencrypt/live/{domain}/privkey.pem"),
        ("include", "/etc/letsencrypt/options-ssl-nginx.conf"),
        ("ssl_dhparam", "/etc/letsencrypt/ssl-dhparams.pem"),
    ]
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

    def build(self, domain, cfg, locations, ssl=False, redirect=False):
        lines = []
        # Redirect block
        if redirect:
            lines.extend([
                "server {",
                f"    if ($host = {domain}) {{ return 301 https://$host$request_uri; }} # certbot",
                "    listen 80;",
                f"    server_name {domain};",
                "    return 404; # certbot",
                "}"
            ])
            return "\n".join(lines)

        # Main server block
        lines.append("server {")
        lines.append(f"    server_name {domain};")
        lines.append(f"    listen {cfg['listen']};")
        # SSL part
        if ssl:
            for k, tpl in self.CERTBOT_SSL_BLOCK:
                lines.append(f"    {k} {tpl.format(domain=domain)}; # certbot")
        # Root or proxy
        if cfg['mode'] == 'proxy':
            lines.append(f"    location {cfg['path']} {{")
            lines.append(f"        proxy_pass {cfg['proxy_pass']};")
            for k, v in self.DEFAULT_PROXY_HEADERS:
                lines.append(f"        {k} {v};")
            lines.append("    }")
        else:
            lines.append(f"    root {cfg['root']};")
            lines.append(f"    index {cfg['index']};")
        # Additional location blocks
        for loc in locations:
            lines.append(f"    location {loc['path']} {{")
            for d, v in loc['directives']:
                lines.append(f"        {d} {v};")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines)


class NginxManager:
    def __init__(self):
        self.avail = SITES_AVAILABLE
        self.enabled = SITES_ENABLED

    def require_root(self):
        if os.geteuid() != 0:
            print("🚨 must be root (sudo).")
            sys.exit(1)

    def list_configs(self):
        print("\n--- Existing Nginx Configs ---")
        confs = sorted(self.avail.glob("*.conf"))
        if not confs:
            print("  (none)\n")
            return

        # Table header
        print(f"{'FILE':<20} {'DOMAIN':<25} {'PORT':<6} {'TYPE':<7} {'SSL':<5}")
        print("-" * 65)
        for conf in confs:
            content = conf.read_text()
            m_name = re.search(r"server_name\s+([^;]+);", content)
            domain = m_name.group(1) if m_name else "-"
            m_listen = re.search(r"listen\s+([\d]+)", content)
            port = m_listen.group(1) if m_listen else "-"
            typ = "proxy" if "proxy_pass" in content else "static"
            ssl = "yes" if "ssl_certificate" in content else "no"
            print(f"{conf.name:<20} {domain:<25} {port:<6} {typ:<7} {ssl:<5}")
        print()

    def write_and_enable(self, domain, full_conf):
        dest = self.avail / f"{domain}.conf"
        dest.write_text(full_conf + "\n")
        print("[+] Written:", dest)
        link = self.enabled / dest.name
        if not link.exists():
            link.symlink_to(dest)
            print("[+] Enabled:", link)

        print("\nTesting nginx syntax...")
        subprocess.run(["nginx", "-t"], check=True)
        print("Reloading nginx...")
        subprocess.run(["nginx", "-s", "reload"], check=True)
        print("✅ Applied!\n")

    def delete_config(self, domain):
        avail_f = self.avail / f"{domain}.conf"
        if not avail_f.exists():
            print(f"⚠️  {domain}.conf not found.")
            return
        enabled_f = self.enabled / avail_f.name
        if enabled_f.exists():
            enabled_f.unlink()
            print(f"[-] Disabled: {enabled_f}")
        avail_f.unlink()
        print(f"[-] Removed: {avail_f}")
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["nginx", "-s", "reload"], check=True)
        print("✅ Configuration removed!\n")


class CLI:
    def __init__(self):
        self.manager = NginxManager()
        self.builder = NginxConfigBuilder()

    def prompt(self, text, default=None):
        if default is None:
            return input(f"{text}: ").strip()
        else:
            resp = input(f"{text} [{default}]: ").strip()
            return resp if resp else default

    def confirm(self, text, default=False):
        yes = {"y", "yes"}
        no = {"n", "no"}
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

    def create_config(self):
        print("\n=== Create a New Nginx Config ===")
        domain = self.prompt("Enter primary domain (e.g. example.com)")
        cfg = {}
        cfg['listen'] = self.prompt("Enter listening port", "80")
        # Choose mode: static or proxy
        mode = self.prompt("Mode? 1=proxy, 2=static (serve files)", "1")
        if mode == '1':
            cfg['mode'] = 'proxy'
            cfg['path'] = self.prompt("Enter proxy path", "/")
            cfg['proxy_pass'] = self.prompt("Enter proxy upstream (e.g. http://localhost:5173)")
        else:
            cfg['mode'] = 'static'
            cfg['root'] = self.prompt("Enter site root directory", "/var/www/html")
            cfg['index'] = self.prompt("Enter index file(s)", "index.html")

        # Additional custom location blocks
        locations = []
        while self.confirm("Add additional location block?", default=False):
            path = self.prompt("  Location path", "/api")
            directives = []
            while True:
                d = self.prompt("    Directive name (blank to finish)")
                if not d:
                    break
                v = self.prompt(f"    Value for {d}")
                directives.append((d, v))
            locations.append({"path": path, "directives": directives})
            print()

        use_ssl = self.confirm("Enable SSL block with Certbot placeholders?", default=True)
        add_redirect = False
        if use_ssl:
            add_redirect = self.confirm("Also generate HTTP->HTTPS redirect block?", default=True)

        # Build blocks
        server_conf = self.builder.build(domain, cfg, locations, ssl=use_ssl, redirect=False)
        blocks = [server_conf]
        if add_redirect:
            blocks.insert(0, self.builder.build(domain, cfg, locations, ssl=False, redirect=True))

        full_conf = "\n\n".join(blocks)
        print("\n--- Preview of Generated Config ---\n")
        print(full_conf)
        print()

        if not self.confirm("Write config and enable?", default=False):
            print("Canceled. No files written.\n")
            return

        self.manager.write_and_enable(domain, full_conf)

    def delete_config(self):
        print("\n=== Delete an Existing Nginx Config ===")
        self.manager.list_configs()
        domain = self.prompt("Enter config name to delete (without .conf)")
        if not self.confirm(f"Are you sure you want to delete {domain}.conf?", default=False):
            print("Canceled.\n")
            return
        self.manager.delete_config(domain)

    def main_loop(self):
        self.manager.require_root()
        while True:
            print("=== Nginx Interactive Manager ===")
            print("1) List configs")
            print("2) Create config")
            print("3) Delete config")
            print("4) Quit")
            choice = self.prompt("Choice", "4")
            if choice == "1":
                self.manager.list_configs()
            elif choice == "2":
                self.create_config()
            elif choice == "3":
                self.delete_config()
            else:
                print("Goodbye!")
                break


if __name__ == "__main__":
    try:
        CLI().main_loop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except subprocess.CalledProcessError:
        print("❌ Nginx error.")
        sys.exit(1)
    except Exception as e:
        print("Unexpected:", e)
        sys.exit(1)
