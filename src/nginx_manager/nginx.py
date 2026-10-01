"""Thin wrapper around the nginx binary: version, ``-t`` and ``-s reload``."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import MissingToolError

DEFAULT_ROOT = Path("/etc/nginx")


@dataclass
class CommandResult:
    ok: bool
    output: str
    command: list[str]


class Nginx:
    def __init__(self, binary: str = "nginx", root_dir: Path = DEFAULT_ROOT) -> None:
        self.binary = binary
        self.root_dir = root_dir
        self._version: tuple[int, int, int] | bool | None = False  # False = not probed yet

    # ---------------------------------------------------------------- helpers
    def path(self) -> str | None:
        return shutil.which(self.binary)

    def require(self) -> str:
        p = self.path()
        if p is None:
            raise MissingToolError(f"nginx binary not found: {self.binary!r} (use --nginx-bin)")
        return p

    def _base_args(self) -> list[str]:
        """With a custom --root-dir, point nginx at <root>/nginx.conf and use it as prefix."""
        if self.root_dir.resolve() == DEFAULT_ROOT:
            return []
        return ["-p", f"{self.root_dir}/", "-c", str(self.root_dir / "nginx.conf")]

    def _run(self, args: list[str]) -> CommandResult:
        cmd = [self.require(), *self._base_args(), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = (proc.stderr + proc.stdout).strip()
        return CommandResult(proc.returncode == 0, output, cmd)

    # ---------------------------------------------------------------- queries
    def version(self) -> tuple[int, int, int] | None:
        if self._version is False:
            self._version = None
            if self.path() is not None:
                proc = subprocess.run(
                    [self.require(), "-v"], capture_output=True, text=True, check=False
                )
                self._version = parse_version(proc.stderr + proc.stdout)
        return self._version  # type: ignore[return-value]

    def test(self) -> CommandResult:
        return self._run(["-t"])

    def reload(self) -> CommandResult:
        return self._run(["-s", "reload"])


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def system_resolvers(resolv_conf: Path = Path("/etc/resolv.conf")) -> list[str]:
    """Nameservers from resolv.conf, bracketed for IPv6, loopback-safe."""
    from . import validators

    out: list[str] = []
    try:
        text = resolv_conf.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            try:
                out.append(validators.resolver(parts[1].split("%")[0]))
            except Exception:
                continue
    return out
