"""Exceptions carrying a process exit code.

Exit codes:
  0  success
  1  validation / generic error
  2  usage error (argparse)
  3  nginx -t or reload failed (changes rolled back when applicable)
  4  permission denied (run with sudo or use --root-dir)
  5  site / file not found
  6  required external tool missing (nginx, certbot, openssl)
"""

from __future__ import annotations


class NginxManagerError(Exception):
    exit_code = 1


class ValidationError(NginxManagerError):
    exit_code = 1


class NginxTestError(NginxManagerError):
    exit_code = 3


class PermissionDeniedError(NginxManagerError):
    exit_code = 4


class NotFoundError(NginxManagerError):
    exit_code = 5


class MissingToolError(NginxManagerError):
    exit_code = 6
