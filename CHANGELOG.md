# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [2.0.0] - 2026-10-01

Complete rewrite. The 1.x interactive script is replaced by an installable package
(`pipx install git+https://github.com/ErwanBAILLON/nginx-manager`) with subcommands,
an interactive menu built on the same code, and a real test suite that runs `nginx -t`.

### Added
- Subcommands: `list [--json]`, `show [--explain]`, `create`, `enable`, `disable`, `delete`,
  `cert`, `test`, `reload`, `doctor`. No arguments -> interactive menu.
- Global options `--root-dir`, `--log-dir`, `--letsencrypt-dir`, `--nginx-bin`, `--certbot-bin`,
  `--no-reload`, `--verbose`. Tests and non-root users work against any directory layout.
- `create` options: `--proxy URL | --static DIR`, `--alias`, `--port`, `--ipv6`, `--proxy-path`,
  `--no-websocket`, `--index`, `--location PATH:DIRECTIVE=VALUE`, `--ssl`, `--ssl-port`,
  `--cert/--key`, `--redirect-http`, `--hsts`, `--csp`, `--rate-limit RATE [--rate-burst]`,
  `--resolver`, `--certbot [--email] [--staging]`, `--force`, `--no-enable`, `--dry-run`, `--yes`.
- `--certbot` flow: write an HTTP-only site, run `certbot certonly --nginx` (certbot never edits
  the file), then re-render the site with the TLS block and reload.
- `doctor`: root check, nginx presence/version, `nginx -t`, directory layout, `nginx.conf`
  includes, broken symlinks in `sites-enabled`, sites available but not enabled, certbot presence,
  certificate expiry per TLS site (`openssl x509 -enddate`), orphan log directories.
- Generated files carry a `# managed by nginx-manager vX, generated <date>` header and the spec
  that produced them as a JSON comment (`show --explain` summarises any config, managed or not).
- WebSocket passthrough through a `map $http_upgrade $connection_upgrade`, so non-WebSocket
  requests no longer force `Connection: upgrade` on the backend.
- Meaningful exit codes (0 ok, 1 validation, 2 usage, 3 nginx test/reload, 4 permission,
  5 not found, 6 missing tool). Colour only on a TTY, no emoji.
- Test suite (pytest): validators, golden-file rendering, filesystem transaction, doctor,
  interactive menu with scripted answers, and integration tests that run the real `nginx -t`
  on proxy / static / TLS (self-signed) / redirect / rate-limit / custom-location configs, as
  non-root. GitHub Actions CI on Python 3.10 and 3.12 with nginx installed.

### Fixed (defects of 1.x)
- Crash after writing an SSL config: `obtain_cert()` did not exist.
- `log_format` emitted inside a server file: nginx rejected it ("not allowed here"). Logging now
  uses the default format; `log_format` belongs to `http` context and is not generated.
- `limit_req zone=one` in every server block without a zone declaration broke `nginx -t`. Rate
  limiting is opt-in (`--rate-limit`) and its zone is managed in `conf.d/nginx-manager.conf`.
- User input (domain, paths, upstream, custom directives) was interpolated raw into the config.
  Every value is now validated strictly and rejected otherwise; `include` is refused in custom
  locations.
- Security headers: obsolete `X-XSS-Protection` removed; the meaningless default CSP with
  `unsafe-inline`/`unsafe-eval` removed (CSP is opt-in via `--csp`); headers live in a per-site
  snippet included in the server block and in every location, so a location-level `add_header`
  no longer silently drops them. HSTS is opt-in (`--hsts`), without `preload`.
- `listen 443 ssl http2` (deprecated since nginx 1.25.1) is emitted only for older nginx;
  1.25.1+ gets `listen 443 ssl;` + `http2 on;`. OCSP stapling uses the resolvers from
  `/etc/resolv.conf` (or `--resolver`) instead of a hardcoded Google DNS.
- `write_and_enable` had three nested symlink fallbacks and deleted files on failure. Writes are
  now atomic (temp file + `os.replace`), every replaced or removed file is backed up with a
  timestamp under `sites-available/.nginx-manager-backups/`, `nginx -t` runs before anything is
  kept, and a failed test restores the previous state. Reload happens only after a passing test.

### Removed
- Dockerfile, docker-compose.yml, entrypoint.sh: an interactive CLI meant to edit the host's
  `/etc/nginx` has no business inside a container.
- `scripts/setup-nginx-conf.sh` (sed on `nginx.conf`): superseded by the managed `conf.d` file.

## [1.x]

Interactive menu script (`sudo ./main.py`). See git history before 2.0.0.
