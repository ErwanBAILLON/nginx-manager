"""
Default settings for the Nginx Manager.
"""

# Nginx file paths
NGINX_PATHS = {
    'sites_available': '/etc/nginx/sites-available',
    'sites_enabled': '/etc/nginx/sites-enabled',
    'logs_dir': '/var/log/nginx',
    'conf_d': '/etc/nginx/conf.d',
    'nginx_conf': '/etc/nginx/nginx.conf',
}

# Certbot paths
CERTBOT_PATHS = {
    'config_dir': '/etc/letsencrypt',
    'live_dir': '/etc/letsencrypt/live',
    'options_ssl': '/etc/letsencrypt/options-ssl-nginx.conf',
    'ssl_dhparams': '/etc/letsencrypt/ssl-dhparams.pem',
}

# Log formats
LOG_FORMATS = {
    'main': '$remote_addr - $remote_user [$time_local] "$request" '
            '$status $body_bytes_sent "$http_referer" '
            '"$http_user_agent" "$http_x_forwarded_for" '
            '$request_time $upstream_response_time $pipe',
    'combined': '$remote_addr - $remote_user [$time_local] "$request" '
                '$status $body_bytes_sent "$http_referer" '
                '"$http_user_agent" "$http_x_forwarded_for"',
}

# Default proxy headers
DEFAULT_PROXY_HEADERS = [
    ('proxy_set_header', 'Host $host'),
    ('proxy_set_header', 'X-Real-IP $remote_addr'),
    ('proxy_set_header', 'X-Forwarded-For $proxy_add_x_forwarded_for'),
    ('proxy_set_header', 'X-Forwarded-Proto $scheme'),
    ('proxy_set_header', 'Upgrade $http_upgrade'),
    ('proxy_set_header', 'Connection "upgrade"'),
    ('proxy_http_version', '1.1'),
    ('proxy_cache_bypass', '$http_upgrade'),
]

# Default SSL parameters
DEFAULT_SSL_PARAMS = {
    'protocols': 'TLSv1.2 TLSv1.3',
    'ciphers': 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384',
    'session_timeout': '1d',
    'session_cache': 'shared:SSL:10m',
    'session_tickets': 'off',
    'prefer_server_ciphers': 'off',
}
