#!/bin/bash
# Script to add rate limiting directives to the main nginx.conf file

NGINX_CONF="/etc/nginx/nginx.conf"
BACKUP_FILE="${NGINX_CONF}.bak"

# Check if we're running as root
if [ "$EUID" -ne 0 ]; then
  echo "This script must be run as root (sudo)."
  exit 1
fi

# Create a backup
echo "Creating backup of ${NGINX_CONF} to ${BACKUP_FILE}"
cp "$NGINX_CONF" "$BACKUP_FILE"

# Check if limit_req_zone directive already exists
if grep -q "limit_req_zone" "$NGINX_CONF"; then
  echo "limit_req_zone directive already exists in nginx.conf"
  
  # Check if the "one" zone is correctly defined
  if grep -q "zone=one:10m" "$NGINX_CONF"; then
    echo "The 'one' zone is correctly defined."
  else
    echo "⚠️ The 'one' zone does not appear to be correctly defined."
    echo "You should manually edit the nginx.conf file to ensure"
    echo "that the directive is correctly defined as follows:"
    echo 'limit_req_zone $binary_remote_addr zone=one:10m rate=1r/s;'
  fi
else
  echo "Adding limit_req_zone directive to nginx.conf"
  
  # Insert directive in http section
  # Use an explicit size (10m) for the shared memory zone
  sed -i '/http {/a \    # Rate limiting zone definition\n    limit_req_zone $binary_remote_addr zone=one:10m rate=1r/s;' "$NGINX_CONF"
  
  echo "Directive added successfully"
fi

# Test configuration
echo "Testing nginx configuration..."
nginx -t

if [ $? -eq 0 ]; then
  echo "✅ Configuration valid!"
  echo "To apply changes: sudo nginx -s reload"
else
  echo "❌ Configuration is invalid. Restoring backup..."
  cp "$BACKUP_FILE" "$NGINX_CONF"
  echo "Backup restored."
  
  echo -e "\n============== MANUAL INSTRUCTIONS ================"
  echo "You will need to manually add this line in the 'http {' section of your nginx.conf:"
  echo -e "\n    limit_req_zone \$binary_remote_addr zone=one:10m rate=1r/s;\n"
  echo "========================================================"
fi

# Create an example configuration file for reference
EXAMPLE_FILE="/etc/nginx/conf.d/rate_limit_example.conf.disabled"
if [ ! -f "$EXAMPLE_FILE" ]; then
  echo "# Example of rate limiting with Nginx" > "$EXAMPLE_FILE"
  echo "# To enable, rename this file to .conf and reload Nginx" >> "$EXAMPLE_FILE"
  echo "" >> "$EXAMPLE_FILE"
  echo "# This part should be in http {}" >> "$EXAMPLE_FILE"
  echo "# limit_req_zone \$binary_remote_addr zone=one:10m rate=1r/s;" >> "$EXAMPLE_FILE"
  echo "" >> "$EXAMPLE_FILE"
  echo "# This part can be in server {}" >> "$EXAMPLE_FILE"
  echo "# limit_req zone=one burst=10 nodelay;" >> "$EXAMPLE_FILE"
  echo "" >> "$EXAMPLE_FILE"
  echo "Example file created: $EXAMPLE_FILE"
fi
