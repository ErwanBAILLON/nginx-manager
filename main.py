#!/usr/bin/env python3
import questionary
import subprocess
from pathlib import Path

SITES_AVAIL = Path("/etc/nginx/sites-available")
SITES_ENABLED = Path("/etc/nginx/sites-enabled")

def ask_basic():
    cfg = {}
    cfg['server_name'] = questionary.text("Domain name(s) (separated by space):").ask()
    cfg['listen'] = questionary.text("Listening port (e.g. 80):", default="80").ask()
    cfg['root'] = questionary.text("Root directory (e.g. /var/www/html):").ask()
    cfg['index'] = questionary.text("Index file(s) (e.g. index.html index.htm):",
                                     default="index.html").ask()
    return cfg

def ask_locations():
    locs = []
    while True:
        add = questionary.confirm("Add a `location` directive?").ask()
        if not add:
            break
        loc = {}
        loc['path'] = questionary.text(" Path (e.g. /api):", default="/").ask()
        kind = questionary.select(" Type:", choices=["try_files", "proxy_pass"]).ask()
        if kind == "try_files":
            loc['directive'] = "try_files"
            loc['value'] = questionary.text(" try_files values (e.g. $uri $uri/ =404):").ask()
        else:
            loc['directive'] = "proxy_pass"
            loc['value'] = questionary.text(" proxy URL (e.g. http://127.0.0.1:3000):").ask()
        locs.append(loc)
    return locs

def build_conf(cfg, locs):
    lines = []
    lines.append("server {")
    lines.append(f"    listen {cfg['listen']};")
    lines.append(f"    server_name {cfg['server_name']};")
    lines.append(f"    root {cfg['root']};")
    lines.append(f"    index {cfg['index']};")
    for loc in locs:
        lines.append(f"    location {loc['path']} {{")
        lines.append(f"        {loc['directive']} {loc['value']};")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)

def write_and_enable(name, content):
    dest = SITES_AVAIL / f"{name}.conf"
    dest.write_text(content + "\n")
    print(f"[+] Written: {dest}")
    link = SITES_ENABLED / dest.name
    if not link.exists():
        link.symlink_to(dest)
        print(f"[+] Enabled: {link}")
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("[+] Nginx reloaded successfully")

def list_configs():
    print("Existing configurations:")
    for p in sorted(SITES_AVAIL.glob("*.conf")):
        print(" -", p.name)

def main():
    print("Welcome to the Nginx configuration generator!")
    action = questionary.select(
        "What do you want to do?",
        choices=[
            "List existing configurations",
            "Create a new configuration",
            "Quit"
        ]).ask()

    if action == "List existing configurations":
        list_configs()
    elif action == "Create a new configuration":
        cfg = ask_basic()
        locs = ask_locations()
        conf_text = build_conf(cfg, locs)
        print("\n== Preview of generated configuration ==\n")
        print(conf_text)
        if questionary.confirm("\nAll good? Write and enable?").ask():
            name = cfg['server_name'].split()[0]
            write_and_enable(name, conf_text)
    else:
        print("Bye!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"An error occurred: {e}")
        exit(1)