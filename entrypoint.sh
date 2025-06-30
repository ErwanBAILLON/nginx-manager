#!/usr/bin/env bash
set -e

# Ensure nginx directories exist
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /var/log/nginx

# Start nginx
nginx

# Execute passed command (default: python3 main.py)
exec "$@"
