"""Filesystem layout and a small transaction helper with backups and rollback."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import PermissionDeniedError
from .nginx import DEFAULT_ROOT


@dataclass(frozen=True)
class Paths:
    root: Path
    log_dir: Path
    letsencrypt_dir: Path

    @classmethod
    def build(
        cls,
        root: Path | None = None,
        log_dir: Path | None = None,
        letsencrypt_dir: Path | None = None,
    ) -> Paths:
        root = (root or DEFAULT_ROOT).absolute()
        default = root == DEFAULT_ROOT
        return cls(
            root=root,
            log_dir=(log_dir or (Path("/var/log/nginx") if default else root / "log")).absolute(),
            letsencrypt_dir=(
                letsencrypt_dir or (Path("/etc/letsencrypt") if default else root / "letsencrypt")
            ).absolute(),
        )

    @property
    def sites_available(self) -> Path:
        return self.root / "sites-available"

    @property
    def sites_enabled(self) -> Path:
        return self.root / "sites-enabled"

    @property
    def conf_d(self) -> Path:
        return self.root / "conf.d"

    @property
    def managed_conf(self) -> Path:
        return self.conf_d / "nginx-manager.conf"

    @property
    def snippets(self) -> Path:
        return self.root / "snippets" / "nginx-manager"

    @property
    def backups(self) -> Path:
        return self.sites_available / ".nginx-manager-backups"

    def available(self, name: str) -> Path:
        return self.sites_available / f"{name}.conf"

    def enabled(self, name: str) -> Path:
        return self.sites_enabled / f"{name}.conf"

    def snippet(self, name: str) -> Path:
        return self.snippets / f"{name}.headers.conf"

    def site_log_dir(self, name: str) -> Path:
        return self.log_dir / name

    def ensure_dirs(self) -> None:
        try:
            for d in (
                self.sites_available,
                self.sites_enabled,
                self.conf_d,
                self.snippets,
                self.backups,
                self.log_dir,
            ):
                d.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise PermissionDeniedError(
                f"cannot create {exc.filename}: permission denied (run with sudo?)"
            ) from exc
        for d in (self.sites_available, self.sites_enabled, self.conf_d, self.snippets):
            if not os.access(d, os.W_OK):
                raise PermissionDeniedError(f"{d} is not writable (run with sudo?)")


def atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    """Write via a temp file in the same directory then ``os.replace`` (never a torn file)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with_suppress_unlink(Path(tmp))
        raise


def _restore(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)


def with_suppress_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


class Transaction:
    """Record filesystem changes so they can be undone if ``nginx -t`` fails.

    Every replaced or removed file is first copied to ``backups_dir`` with a timestamp;
    the backup is kept even on success (it is the user's safety net).
    """

    def __init__(self, backups_dir: Path) -> None:
        self.backups_dir = backups_dir
        self._undo: list[Callable[[], None]] = []
        self.backups: list[Path] = []

    def _backup(self, path: Path) -> Path | None:
        if not path.exists() or path.is_dir():
            return None
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = self.backups_dir / f"{path.name}.{stamp}.bak"
        shutil.copy2(path, dest)
        self.backups.append(dest)
        return dest

    def write(self, path: Path, content: str) -> None:
        if path.is_file() and path.read_text() == content:
            return  # unchanged: no write, no backup noise
        backup = self._backup(path)
        existed = path.exists()
        atomic_write(path, content)

        def undo() -> None:
            if backup is not None:
                shutil.copy2(backup, path)
            elif not existed:
                with_suppress_unlink(path)

        self._undo.append(undo)

    def remove(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_symlink():
            target = os.readlink(path)
            path.unlink()
            self._undo.append(lambda: os.symlink(target, path))
            return
        backup = self._backup(path)
        path.unlink()
        if backup is not None:
            self._undo.append(lambda: _restore(backup, path))

    def symlink(self, link: Path, target: Path) -> None:
        self.remove(link)
        rel = os.path.relpath(target, link.parent)
        os.symlink(rel, link)
        self._undo.append(lambda: with_suppress_unlink(link))

    def mkdir(self, path: Path) -> None:
        if path.exists():
            return
        path.mkdir(parents=True)

        def undo() -> None:
            with contextlib.suppress(OSError):
                path.rmdir()

        self._undo.append(undo)

    def rollback(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()
