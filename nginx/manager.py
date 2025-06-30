import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from config.default_settings import NGINX_PATHS
from utils.system import run_command

class NginxManager:
    """Manages Nginx configuration files and operations."""
    
    def __init__(self):
        self.avail = Path(NGINX_PATHS['sites_available'])
        self.enabled = Path(NGINX_PATHS['sites_enabled'])
        self.logs_dir = Path(NGINX_PATHS['logs_dir'])
        
    def require_root(self) -> bool:
        """Check if the script is running with root privileges."""
        if os.geteuid() != 0:
            print("🚨 This operation requires root privileges (sudo).")
            return False
        return True

    def ensure_directories(self) -> bool:
        """Ensure all required Nginx directories exist."""
        try:
            for dir_path in [self.avail, self.enabled, self.logs_dir]:
                if not dir_path.exists():
                    print(f"Creating directory: {dir_path}")
                    dir_path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"❌ Error creating directories: {e}")
            return False

    def list_configs(self) -> List[Dict[str, str]]:
        """List all available Nginx configurations and their details."""
        print("\n--- Existing Nginx Configs ---")
        confs = sorted(self.avail.glob("*.conf"))
        if not confs:
            print("  (none)\n")
            return []

        print(f"{'FILE':<20} {'DOMAIN':<25} {'PORT':<6} {'TYPE':<7} {'SSL':<5}")
        print("-" * 65)
        
        result = []
        for conf in confs:
            content = conf.read_text()
            m_name = re.search(r"server_name\s+([^;]+);", content)
            domain = m_name.group(1).strip() if m_name else "-"
            m_listen = re.search(r"listen\s+([\d]+)", content)
            port = m_listen.group(1) if m_listen else "-"
            typ = "proxy" if "proxy_pass" in content else "static"
            ssl = "yes" if "ssl_certificate" in content else "no"
            print(f"{conf.name:<20} {domain:<25} {port:<6} {typ:<7} {ssl:<5}")
            
            result.append({
                "name": conf.name,
                "domain": domain,
                "port": port,
                "type": typ,
                "ssl": ssl == "yes"
            })
        print()
        return result

    def write_and_enable(self, domain: str, full_conf: str) -> bool:
        """Write and enable a Nginx configuration for a domain."""
        if not self.ensure_directories():
            return False
            
        safe_domain = self._sanitize_domain(domain)
        dest = self.avail / f"{safe_domain}.conf"
        
        try:
            log_dir = self.logs_dir / safe_domain
            log_dir.mkdir(exist_ok=True, parents=True)
            
            dest.write_text(full_conf + "\n")
            print(f"[+] Written: {dest}")
            
            link = self.enabled / dest.name
            
            if link.exists():
                if link.is_symlink():
                    link.unlink()
                    print(f"[-] Removed existing symlink: {link}")
                else:
                    backup = link.with_suffix('.conf.bak')
                    shutil.move(link, backup)
                    print(f"[-] Backed up regular file: {link} → {backup}")
            
            if not dest.exists():
                print(f"❌ Error: Target file {dest} does not exist!")
                return False
            
            try:
                relative_path = os.path.relpath(dest, link.parent)
                os.symlink(relative_path, link)
                print(f"[+] Enabled: {link} → {relative_path}")
            except Exception as e1:
                print(f"Could not create relative symlink: {e1}")
                try:
                    os.symlink(dest.absolute(), link)
                    print(f"[+] Enabled: {link} → {dest.absolute()}")
                except Exception as e2:
                    print(f"Could not create absolute symlink: {e2}")
                    try:
                        if run_command(["ln", "-sf", str(dest.absolute()), str(link.absolute())]):
                            print(f"[+] Enabled using ln command: {link}")
                        else:
                            raise Exception("ln command failed")
                    except Exception as e3:
                        print(f"❌ All symlink methods failed! {e3}")
                        if dest.exists():
                            dest.unlink()
                        return False

            if not link.exists():
                print(f"❌ Symlink creation failed: {link} does not exist")
                if dest.exists():
                    dest.unlink()
                return False
                
            target_path = Path(os.path.realpath(link))
            if not target_path.exists():
                print(f"❌ Symlink target does not exist: {link} → {target_path}")
                link.unlink()
                if dest.exists():
                    dest.unlink()
                return False

            print("\nTesting nginx syntax...")
            if not run_command(["nginx", "-t"]):
                print("❌ Nginx configuration test failed. Rolling back changes...")
                if link.exists():
                    link.unlink()
                if dest.exists():
                    dest.unlink()
                return False
                
            print("Reloading nginx...")
            if not run_command(["nginx", "-s", "reload"]):
                print("❌ Nginx reload failed.")
                return False
                
            print("✅ Applied!\n")
            return True
            
        except Exception as e:
            print(f"❌ Error applying configuration: {e}")
            if dest.exists():
                dest.unlink()
            return False

    def delete_config(self, domain: str) -> bool:
        """Delete a Nginx configuration for a domain."""
        safe_domain = self._sanitize_domain(domain)
        avail_f = self.avail / f"{safe_domain}.conf"
        enabled_f = self.enabled / f"{safe_domain}.conf"
        
        try:
            if not avail_f.exists() and not enabled_f.exists():
                print(f"⚠️ No configuration found for {domain}")
                return False
                
            if enabled_f.exists():
                enabled_f.unlink()
                print(f"[-] Disabled: {enabled_f}")
                
            if avail_f.exists():
                avail_f.unlink()
                print(f"[-] Removed: {avail_f}")
            
            if enabled_f.exists() and enabled_f.is_symlink():
                target = Path(os.readlink(enabled_f))
                if not target.exists():
                    enabled_f.unlink()
                    print(f"[-] Removed broken symlink: {enabled_f}")
            
            if not run_command(["nginx", "-t"]):
                print("⚠️ Nginx configuration test failed after deletion.")
                return False
                
            if not run_command(["nginx", "-s", "reload"]):
                print("⚠️ Nginx reload failed after deletion.")
                return False
            
            print("✅ Configuration removed!\n")
            return True
            
        except Exception as e:
            print(f"❌ Error removing configuration: {e}")
            return False

    def show_config(self, domain: str) -> Optional[str]:
        """Show the configuration for a domain."""
        safe_domain = self._sanitize_domain(domain)
        conf_file = self.avail / f"{safe_domain}.conf"
        
        if not conf_file.exists():
            print(f"⚠️ {safe_domain}.conf not found in sites-available.")
            enabled_file = self.enabled / f"{safe_domain}.conf"
            if enabled_file.exists():
                if enabled_file.is_symlink():
                    target = Path(os.readlink(enabled_file))
                    print(f"⚠️ Found only as symlink in sites-enabled pointing to {target}")
                else:
                    content = enabled_file.read_text()
                    print(f"\n--- {domain}.conf content (from sites-enabled) ---\n")
                    print(content)
                    print()
                    return content
            return None
            
        content = conf_file.read_text()
        print(f"\n--- {domain}.conf content ---\n")
        print(content)
        print()
        return content

    def _sanitize_domain(self, domain: str) -> str:
        """Sanitize domain name for safe filename usage."""
        return re.sub(r'[^\w.-]', '_', domain)
