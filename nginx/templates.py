"""
High-quality Nginx configuration templates based on best practices.
"""

# Main log format with detailed information
LOG_FORMAT_MAIN = """# Log format definition
log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                '$status $body_bytes_sent "$http_referer" '
                '"$http_user_agent" "$http_x_forwarded_for"';
"""

# Complete server block template
SERVER_BLOCK_TEMPLATE = """server {{
    listen {port};
    server_name {domain};
    
{static_directives}
{log_config}
    
    # Security settings
{security_headers}
    
    # Rate limiting (requires limit_req_zone in http context of nginx.conf)
{rate_limiting}
    
{locations}

{ssl_config}
}}"""

# HTTP to HTTPS redirect server block
REDIRECT_SERVER_BLOCK = """server {{
    listen 80;
    server_name {domain};
    
    # Redirect all HTTP traffic to HTTPS
    return 301 https://$host$request_uri;
}}
"""

# Proxy location block with optimized settings
PROXY_LOCATION_BLOCK = """location {path} {{
    proxy_pass {proxy_pass};
    
    # Proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket support
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Proxy optimizations
    proxy_buffers 16 16k;
    proxy_buffer_size 16k;
    proxy_http_version 1.1;
    proxy_redirect off;
    
    # Timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}}"""

# Static file serving directives
STATIC_SERVER_DIRECTIVES = """    # Static site configuration
    root {root};
    index {index};
    
    # Serve static files efficiently
    location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {{
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }}
    
    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
    }}"""

# Security headers based on best practices
SECURITY_HEADERS = [
    "# Security headers",
    "add_header X-Content-Type-Options nosniff;",
    "add_header X-Frame-Options SAMEORIGIN;",
    "add_header X-XSS-Protection \"1; mode=block\";",
    "add_header Referrer-Policy no-referrer-when-downgrade;",
    "add_header Content-Security-Policy \"default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval';\";",
    "add_header Permissions-Policy \"camera=(), microphone=(), geolocation=()\";"
]

# SSL configuration with modern ciphers and settings
SSL_CONFIG_BLOCK = [
    ("listen", "443 ssl http2"),
    ("ssl_certificate", "/etc/letsencrypt/live/{domain}/fullchain.pem"),
    ("ssl_certificate_key", "/etc/letsencrypt/live/{domain}/privkey.pem"),
    ("ssl_session_timeout", "1d"),
    ("ssl_session_cache", "shared:SSL:10m"),
    ("ssl_session_tickets", "off"),
    ("ssl_protocols", "TLSv1.2 TLSv1.3"),
    ("ssl_ciphers", "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384"),
    ("ssl_prefer_server_ciphers", "off"),
    ("include", "/etc/letsencrypt/options-ssl-nginx.conf"),
    ("ssl_dhparam", "/etc/letsencrypt/ssl-dhparams.pem"),
    ("ssl_stapling", "on"),
    ("ssl_stapling_verify", "on"),
    ("resolver", "8.8.8.8 8.8.4.4 valid=60s"),
    ("resolver_timeout", "2s")
]

# Rate limiting configuration - ONLY include limit_req in server blocks
RATE_LIMITING = [
    "# Rate limiting",
    "limit_req zone=one burst=10 nodelay;"  # Removed limit_req_zone directive - this must be in http context
]

