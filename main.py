#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SITES_ENABLED   = Path("/etc/nginx/sites-enabled")

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

def build_server_block(cfg, locations):
    lines = ["server {"]
    lines.append(f"    listen {cfg['listen']};")
    lines.append(f"    server_name {cfg['server_name']};")
    lines.append(f"    root {cfg['root']};")
    lines.append(f"    index {cfg['index']};")
    for loc in locations:
        lines.append(f"    location {loc['path']} {{")
        for directive, value in loc["directives"]:
            lines.append(f"        {directive} {value};")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)

def create_config():
    print("\n=== Create a New Nginx Config ===")
    cfg = {}
    cfg['server_name'] = prompt("Enter domain name(s) (space-separated)")
    cfg['listen']      = prompt("Enter listening port", "80")
    cfg['root']        = prompt("Enter site root directory", "/var/www/html")
    cfg['index']       = prompt("Enter index file(s) (space-separated)", "index.html")

    locations = []
    while True:
        if not confirm("Add a location block?", default=False):
            break
        path = prompt("  Location path", "/")
        # collect multiple directives per location
        directives = []
        while True:
            print("    Choose a directive to add:")
            print("      1) try_files")
            print("      2) proxy_pass")
            print("      3) add custom (e.g. access_log, expires)")
            print("      4) done with this location")
            choice = prompt("    Select 1–4", "4")
            if choice == "1":
                val = prompt("      try_files arguments (e.g. $uri $uri/ =404)")
                directives.append(("try_files", val))
            elif choice == "2":
                val = prompt("      proxy_pass URL (e.g. http://127.0.0.1:3000)")
                directives.append(("proxy_pass", val))
            elif choice == "3":
                d = prompt("      Directive name (e.g. expires)")
                v = prompt(f"      Value for {d}")
                directives.append((d, v))
            else:
                break
        locations.append({"path": path, "directives": directives})
        print()

    server_block = build_server_block(cfg, locations)
    print("\n--- Preview of Generated Config ---\n")
    print(server_block)
    print()
    if not confirm("Write this config to disk and enable it?", default=False):
        print("Canceled. No files were written.\n")
        return

    name = cfg['server_name'].split()[0]
    dest = SITES_AVAILABLE / f"{name}.conf"
    dest.write_text(server_block + "\n")
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
