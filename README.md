# nginx-manager

Generate, validate and manage nginx virtual hosts from the command line, safely.

`nginx-manager` writes one file per site in `sites-available/`, enables it with a symlink,
runs `nginx -t` **before** keeping anything, and reloads nginx only when the test passes.
Every file it replaces or removes is backed up first. It produces readable, auditable
configs for the two common cases (reverse proxy, static files) with sane TLS, security
headers, optional rate limiting and WebSocket passthrough.

Pure Python standard library, Python 3.10+, no runtime dependency. GPL-3.0.

## Install

```bash
pipx install git+https://github.com/ErwanBAILLON/nginx-manager
# or
pip install --user git+https://github.com/ErwanBAILLON/nginx-manager
```

Requirements on the host: nginx (any 1.18+; 1.25.1+ gets `http2 on;`), optionally certbot with
the nginx plugin (`apt install certbot python3-certbot-nginx`) for `cert` / `--certbot`, and
openssl for certificate expiry in `doctor`. Writing to `/etc/nginx` needs root: run with `sudo`.

## Quickstart

```bash
# Reverse proxy, plain HTTP
sudo nginx-manager create app.example.com --proxy http://127.0.0.1:3000

# Same, with Let's Encrypt: writes the HTTP site, runs certbot certonly --nginx,
# then re-renders the site with TLS, redirect and HSTS
sudo nginx-manager create app.example.com --proxy http://127.0.0.1:3000 \
    --certbot --email ops@example.com --redirect-http --hsts

# Static site with an extra API location and rate limiting
sudo nginx-manager create www.example.org --static /var/www/example --alias example.org \
    --location /api:proxy_pass=http://127.0.0.1:4000 \
    --location '/api:proxy_set_header=Host $host' \
    --rate-limit 10r/s

# TLS with a certificate you already have
sudo nginx-manager create app.example.com --proxy http://127.0.0.1:3000 \
    --ssl --cert /etc/ssl/app/fullchain.pem --key /etc/ssl/app/privkey.pem

sudo nginx-manager list                 # or --json
sudo nginx-manager show app.example.com --explain
sudo nginx-manager disable app.example.com
sudo nginx-manager enable app.example.com
sudo nginx-manager delete app.example.com     # --keep-logs to keep /var/log/nginx/<site>/
sudo nginx-manager cert app.example.com --email ops@example.com   # certbot certonly --nginx
sudo nginx-manager test                 # nginx -t
sudo nginx-manager reload               # nginx -t, then nginx -s reload
sudo nginx-manager doctor               # health report (see below)
sudo nginx-manager                      # interactive menu, same features
```

`create` prints the generated config and asks for confirmation; `--yes` skips the question,
`--dry-run` prints without writing. Re-creating an existing site requires `--force` (the old
file is backed up).

Global options, usable before or after the subcommand: `--root-dir DIR` (default `/etc/nginx`),
`--log-dir`, `--letsencrypt-dir`, `--nginx-bin`, `--certbot-bin`, `--no-reload`, `--verbose`.
With a custom `--root-dir`, nginx is invoked as `nginx -p DIR/ -c DIR/nginx.conf`, which is how
the test suite runs the real binary as a normal user.

### `doctor`

```
warn  privileges: not root: writes to /etc/nginx will fail
ok    nginx binary: /usr/sbin/nginx (version 1.24.0)
ok    nginx -t: nginx: configuration file /etc/nginx/nginx.conf test is successful
ok    sites-available: /etc/nginx/sites-available
ok    sites-enabled: /etc/nginx/sites-enabled
ok    conf.d: /etc/nginx/conf.d
ok    log dir: /var/log/nginx
warn  available but not enabled: old.example.com.conf
ok    certbot: /usr/bin/certbot
warn  certificate app.example.com: expires 2026-10-03 (1 days)
warn  orphan log dir: /var/log/nginx/removed.example.com

11 checks, overall: warn
```

Exit code 1 when any check fails (missing nginx, broken symlink, expired certificate...).
The certificate check reads the `ssl_certificate` directive of each TLS site (managed or
hand-written); a site whose certificate comes from an include is reported as a warning, not a
failure.

## What gets generated

`create app.example.com --proxy http://127.0.0.1:3000 --ssl --redirect-http --hsts
--rate-limit 10r/s --location /api:proxy_pass=http://127.0.0.1:4000` produces three files.

`sites-available/app.example.com.conf` (header and spec comment trimmed):

```nginx
# Plain HTTP: redirect everything to HTTPS
server {
    listen 80;
    server_name app.example.com;
    access_log /var/log/nginx/app.example.com/access.log;
    error_log  /var/log/nginx/app.example.com/error.log warn;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.example.com;

    access_log /var/log/nginx/app.example.com/access.log;
    error_log  /var/log/nginx/app.example.com/error.log warn;

    # Security headers (also included in every location below)
    include /etc/nginx/snippets/nginx-manager/app.example.com.headers.conf;

    # Rate limiting: 10r/s per client IP, burst 20
    limit_req zone=nm_app_example_com burst=20 nodelay;
    limit_req_status 429;

    # TLS
    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;  # certbot's maintained TLS parameters
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        # WebSocket passthrough (map in conf.d/nginx-manager.conf)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_buffers 16 16k;
        proxy_buffer_size 16k;
        include /etc/nginx/snippets/nginx-manager/app.example.com.headers.conf;
    }

    location /api {
        proxy_pass http://127.0.0.1:4000;
        include /etc/nginx/snippets/nginx-manager/app.example.com.headers.conf;
    }
}
```

`snippets/nginx-manager/app.example.com.headers.conf`: `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, plus `Strict-Transport-Security`
with `--hsts` and `Content-Security-Policy` with `--csp`. nginx discards inherited `add_header`
directives as soon as a location defines its own, so the snippet is included in the server block
and in every location.

`conf.d/nginx-manager.conf` (http context, shared by all sites): the
`map $http_upgrade $connection_upgrade` used for WebSockets and one `limit_req_zone` per site
that opted into `--rate-limit`. The file is regenerated on every create/delete.

When certbot's `options-ssl-nginx.conf` is absent, an inline TLS 1.2/1.3 cipher set is emitted
instead. When nginx is older than 1.25.1, `listen 443 ssl http2;` is used instead of `http2 on;`.
OCSP stapling is opt-in (`--ocsp-stapling [--resolver IP]`, resolver from `/etc/resolv.conf` by
default): Let's Encrypt stopped putting OCSP URLs in its certificates in 2025, so stapling on
by default would only make `nginx -t` print `"ssl_stapling" ignored` on every reload.

Static sites get `root`/`index`, `try_files $uri $uri/ =404`, 30-day caching for assets and a
`deny all` on dotfiles (except `.well-known`).

## Safety guarantees

- **Validated input.** Domain, aliases, ports, paths, upstream URL, directive names and values,
  rates, CSP and resolvers are checked against strict patterns and rejected otherwise; nothing is
  "sanitised" into the config. `include` is refused in custom locations.
- **Atomic writes.** Files are written to a temp file in the same directory, fsynced, then
  `os.replace`d. A crash never leaves a half-written config.
- **Backups.** Every file about to be replaced or removed is copied to
  `sites-available/.nginx-manager-backups/<file>.<timestamp>.bak` first. Backups are never
  deleted by the tool.
- **Test before keep.** After writing and enabling, `nginx -t` runs. On failure all changes of the
  operation are rolled back (previous files restored, new files and symlinks removed) and the
  command exits 3. The reload happens only after a passing test.
- **Pre-flight.** `--ssl` without an existing certificate file is refused before writing (exit 5),
  with the hint to use `cert` or `--certbot`.
- **certbot never edits your config.** `cert` and `--certbot` use `certbot certonly --nginx`;
  the TLS block is rendered by nginx-manager from a known template.

Exit codes: 0 ok, 1 validation error, 2 usage, 3 nginx -t or reload failed, 4 permission
denied, 5 not found, 6 missing tool (nginx, certbot).

## Limitations

- Debian/Ubuntu layout only (`sites-available` / `sites-enabled` / `conf.d` / `snippets`).
  `nginx.conf` must include `conf.d/*.conf` and `sites-enabled/*` (the Debian default does;
  `doctor` warns otherwise).
- One site file per domain (plus aliases). Multiple server blocks with different roots, upstream
  groups, caching, auth or fastcgi are out of scope: write those by hand, `list`/`show`/`enable`/
  `disable`/`delete`/`doctor` still work on hand-written files.
- `nginx -t` binds the listen ports, so as non-root the test can only pass for ports >= 1024.
  This matters for the test suite and `--root-dir` experiments, not for `sudo` use.
- HSTS is sent without `preload`; submitting a domain to the preload list is irreversible and is
  left as a deliberate manual step.
- Rate limiting keys on `$binary_remote_addr`; behind another proxy you need `real_ip` handling
  in `http` context, which this tool does not manage.
- No Windows, no nginx Plus specifics.

## Development

```bash
git clone https://github.com/ErwanBAILLON/nginx-manager && cd nginx-manager
uv venv && uv pip install -e '.[dev]'        # or: python -m venv .venv && pip install -e '.[dev]'
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run pytest --cov                           # integration tests need /usr/sbin/nginx and openssl
UPDATE_GOLDEN=1 uv run pytest tests/test_spec_templates.py   # refresh golden files after a template change
```

Integration tests build a throwaway nginx prefix under `tmp_path`, point `--root-dir` at it and
run the real `nginx -t` (no root, no running nginx needed). CI does the same on Ubuntu with
Python 3.10 and 3.12.

Layout: `src/nginx_manager/` — `validators` (input rules), `spec` (SiteSpec dataclass),
`templates` (config rendering), `fs` (paths, atomic write, transaction/rollback), `nginx`
(binary wrapper), `manager` (operations), `doctor`, `certbot`, `cli`, `interactive`, `ui`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
