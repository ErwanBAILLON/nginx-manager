#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour permettre les importations relatives
sys.path.insert(0, str(Path(__file__).parent))

from cli.interface import CLI
from utils.system import check_environment

def main():
    """Main entry point for the Nginx Manager application."""
    # Check environment prerequisites
    if not check_environment():
        sys.exit(1)
    
    try:
        CLI().main_loop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
