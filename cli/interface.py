import sys
from typing import List, Dict, Any, Optional

from nginx.manager import NginxManager
from nginx.config_builder import NginxConfigBuilder
from cli.validators import validate_domain, validate_port, validate_path

class CLI:
    """Command-line interface for the Nginx Manager."""

    def __init__(self):
        self.manager = NginxManager()
        self.builder = NginxConfigBuilder()

    def prompt(self, text: str, default: Optional[str] = None) -> str:
        """Prompt the user for input with optional default value."""
        if default is None:
            return input(f"{text}: ").strip()
        else:
            resp = input(f"{text} [{default}]: ").strip()
            return resp if resp else default

    def confirm(self, text: str, default: bool = False) -> bool:
        """Ask user for yes/no confirmation."""
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

    def create_config(self) -> None:
        """Create a new Nginx configuration."""
        print("\n=== Create a New Nginx Config ===")
        
        while True:
            domain = self.prompt("Enter primary domain (e.g. example.com)")
            if validate_domain(domain):
                break
            print("⚠️  Invalid domain. Please enter a valid domain name.")
        
        cfg = {}
        
        while True:
            port = self.prompt("Enter listening port", "80")
            if validate_port(port):
                cfg['listen'] = port
                break
            print("⚠️  Invalid port. Please enter a valid port number.")
        
        mode = self.prompt("Mode? 1=proxy, 2=static (serve files)", "1")
        
        if mode == '1':
            cfg['mode'] = 'proxy'
            
            while True:
                path = self.prompt("Enter proxy path", "/")
                if validate_path(path):
                    cfg['path'] = path
                    break
                print("⚠️  Invalid path. Path must start with /")
            
            cfg['proxy_pass'] = self.prompt("Enter proxy upstream (e.g. http://localhost:5173)")
            
        else:
            cfg['mode'] = 'static'
            cfg['root'] = self.prompt("Enter site root directory", "/var/www/html")
            cfg['index'] = self.prompt("Enter index file(s)", "index.html")

        locations = []
        while self.confirm("Add additional location block?", default=False):
            while True:
                path = self.prompt("  Location path", "/api")
                if validate_path(path):
                    break
                print("⚠️  Invalid path. Path must start with /")
                
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

        if not self.manager.write_and_enable(domain, full_conf):
            return

        if use_ssl and self.confirm(f"Run Certbot now? (will execute: sudo certbot --nginx -d {domain})", default=True):
            self.manager.obtain_cert(domain)

    def delete_config(self) -> None:
        """Delete an existing Nginx configuration."""
        print("\n=== Delete an Existing Nginx Config ===")
        self.manager.list_configs()
        domain = self.prompt("Enter config name to delete (without .conf)")
        if not domain:
            print("⚠️  No config name provided. Canceling.\n")
            return
        if not self.confirm(f"Are you sure you want to delete {domain}.conf?", default=False):
            print("Canceled.\n")
            return
        self.manager.delete_config(domain)

    def show_config(self) -> None:
        """Show the contents of a configuration file."""
        print("\n=== View Nginx Config Details ===")
        self.manager.list_configs()
        domain = self.prompt("Enter config name to view (without .conf)")
        if not domain:
            print("⚠️  No config name provided.\n")
            return
        self.manager.show_config(domain)

    def main_loop(self) -> None:
        """Main application loop."""
        if not self.manager.require_root():
            sys.exit(1)
            
        while True:
            print("=== Nginx Interactive Manager ===")
            print("1) List configs")
            print("2) Create config")
            print("3) Show config details")
            print("4) Delete config") 
            print("5) Quit")
            choice = self.prompt("Choice", "5")

            if choice == "1":
                self.manager.list_configs()
            elif choice == "2":
                self.create_config()
            elif choice == "3":
                self.show_config()
            elif choice == "4":
                self.delete_config()
            else:
                print("Goodbye!")
                break
