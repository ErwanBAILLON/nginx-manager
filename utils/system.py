import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional

def check_environment() -> bool:
    """
    Check if the environment meets the requirements.
    
    Returns:
        True if environment is valid, False otherwise
    """
    # Vérification des privilèges root
    if os.geteuid() != 0:
        print("🚨 This tool requires root privileges. Please run with sudo.")
        return False
        
    # Vérification de l'installation de nginx
    nginx_installed = shutil.which("nginx") is not None
    if not nginx_installed:
        print("❌ Nginx is not installed or not in PATH.")
        return False
    
    # Vérification des répertoires Nginx
    nginx_dirs = [
        Path('/etc/nginx'),
        Path('/etc/nginx/sites-available'),
        Path('/etc/nginx/sites-enabled'),
        Path('/var/log/nginx')
    ]
    
    # Check for inconsistent symlinks in sites-enabled
    sites_enabled = Path('/etc/nginx/sites-enabled')
    sites_available = Path('/etc/nginx/sites-available')
    if sites_enabled.exists():
        for symlink in sites_enabled.glob('*.conf'):
            if symlink.is_symlink():
                target = Path(os.readlink(symlink))
                if not target.is_absolute():
                    # Convert relative path to absolute
                    target = (symlink.parent / target).resolve()
                if not target.exists():
                    print(f"⚠️ Found broken symlink: {symlink} → {target}")
                    choice = input(f"Remove broken symlink? (y/N): ").strip().lower()
                    if choice in ('y', 'yes'):
                        try:
                            symlink.unlink()
                            print(f"[-] Removed broken symlink: {symlink}")
                        except Exception as e:
                            print(f"❌ Could not remove symlink: {e}")
    
    # Create missing directories
    missing_dirs = []
    for dir_path in nginx_dirs:
        if not dir_path.exists():
            missing_dirs.append(dir_path)
    
    if missing_dirs:
        print("⚠️ Some required Nginx directories are missing.")
        choice = input("Create missing directories? (Y/n): ").strip().lower()
        if not choice or choice in ('y', 'yes'):
            for dir_path in missing_dirs:
                try:
                    print(f"Creating {dir_path}")
                    dir_path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    print(f"❌ Failed to create directory {dir_path}: {e}")
                    return False
        else:
            print("❌ Cannot continue without required directories.")
            return False
    
    # Vérification de certbot (optionnel)
    certbot_installed = shutil.which("certbot") is not None
    if not certbot_installed:
        print("⚠️ Certbot is not installed. SSL certificate management will not be available.")
    
    return True

def run_command(cmd: List[str]) -> bool:
    """
    Run a command and handle exceptions safely.
    
    Args:
        cmd: Command list to run
        
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        print(f"Running: {' '.join(cmd)}")
        
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        
        if process.returncode != 0:
            print(f"Command failed with exit code {process.returncode}")
            if process.stderr:
                print(f"Error output: {process.stderr.strip()}")
            if process.stdout:
                print(f"Standard output: {process.stdout.strip()}")
            return False
            
        return True
        
    except Exception as e:
        print(f"Error executing command {' '.join(cmd)}: {e}")
        return False
        
def is_root() -> bool:
    """
    Check if the script is running with root privileges.
    
    Returns:
        True if running as root, False otherwise
    """
    return os.geteuid() == 0
