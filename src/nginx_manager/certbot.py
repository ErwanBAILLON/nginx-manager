"""certbot wrapper: obtain a certificate without letting certbot rewrite our config.

``certbot certonly --nginx`` uses the running nginx to answer the HTTP-01 challenge but does
not edit the server file; nginx-manager then renders the TLS block itself.
"""

from __future__ import annotations

import shutil
import subprocess

from .errors import MissingToolError


def build_command(
    domain: str,
    email: str | None = None,
    staging: bool = False,
    binary: str = "certbot",
    aliases: list[str] | None = None,
) -> list[str]:
    cmd = [binary, "certonly", "--nginx", "--non-interactive", "--agree-tos", "-d", domain]
    for alias in aliases or []:
        cmd += ["-d", alias]
    if email:
        cmd += ["--email", email]
    else:
        cmd.append("--register-unsafely-without-email")
    if staging:
        cmd.append("--staging")
    return cmd


def require(binary: str = "certbot") -> str:
    path = shutil.which(binary)
    if path is None:
        raise MissingToolError(
            "certbot not found. Install it (apt install certbot python3-certbot-nginx) "
            "or obtain a certificate another way and pass --cert/--key."
        )
    return path


def run(cmd: list[str]) -> int:
    """Run certbot with inherited stdio so its own output is visible."""
    return subprocess.run(cmd, check=False).returncode
