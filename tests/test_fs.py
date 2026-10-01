from __future__ import annotations

import os
from pathlib import Path

import pytest

from nginx_manager.errors import PermissionDeniedError
from nginx_manager.fs import Paths, Transaction, atomic_write


def test_paths_defaults() -> None:
    p = Paths.build()
    assert p.root == Path("/etc/nginx")
    assert p.log_dir == Path("/var/log/nginx")
    assert p.letsencrypt_dir == Path("/etc/letsencrypt")
    assert p.available("x") == Path("/etc/nginx/sites-available/x.conf")
    assert p.backups == Path("/etc/nginx/sites-available/.nginx-manager-backups")


def test_paths_custom_root(tmp_path: Path) -> None:
    p = Paths.build(root=tmp_path, log_dir=tmp_path / "L")
    assert p.log_dir == tmp_path / "L"
    assert p.letsencrypt_dir == tmp_path / "letsencrypt"
    assert p.snippet("a") == tmp_path / "snippets" / "nginx-manager" / "a.headers.conf"
    p.ensure_dirs()
    assert p.sites_enabled.is_dir() and p.backups.is_dir() and p.log_dir.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_ensure_dirs_permission(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        with pytest.raises(PermissionDeniedError):
            Paths.build(root=ro / "nginx").ensure_dirs()
        p = Paths.build(root=tmp_path / "ok")
        p.ensure_dirs()
        p.sites_enabled.chmod(0o500)
        with pytest.raises(PermissionDeniedError, match="not writable"):
            p.ensure_dirs()
    finally:
        ro.chmod(0o700)
        (tmp_path / "ok" / "sites-enabled").chmod(0o700)


def test_atomic_write(tmp_path: Path) -> None:
    target = tmp_path / "f.conf"
    atomic_write(target, "one\n")
    atomic_write(target, "two\n", mode=0o600)
    assert target.read_text() == "two\n"
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["f.conf"]  # no temp file left behind


def test_transaction_write_and_rollback(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    existing = tmp_path / "existing.conf"
    existing.write_text("old\n")
    fresh = tmp_path / "fresh.conf"
    tx = Transaction(backups)
    tx.write(existing, "new\n")
    tx.write(fresh, "hello\n")
    tx.write(fresh, "hello\n")  # unchanged: no extra backup
    assert existing.read_text() == "new\n" and fresh.exists()
    assert len(tx.backups) == 1 and tx.backups[0].read_text() == "old\n"
    tx.rollback()
    assert existing.read_text() == "old\n"
    assert not fresh.exists()
    assert tx.backups[0].exists()  # backups are kept


def test_transaction_symlink_remove_mkdir(tmp_path: Path) -> None:
    tx = Transaction(tmp_path / "b")
    target = tmp_path / "t.conf"
    target.write_text("x\n")
    other = tmp_path / "o.conf"
    other.write_text("y\n")
    link = tmp_path / "link.conf"
    os.symlink(other, link)
    d = tmp_path / "newdir"
    tx.mkdir(d)
    tx.mkdir(d)  # already exists: no-op
    tx.symlink(link, target)  # replaces the old symlink
    assert link.resolve() == target
    tx.remove(other)
    tx.remove(tmp_path / "missing.conf")  # no-op
    assert not other.exists()
    tx.rollback()
    assert other.read_text() == "y\n"
    assert os.readlink(link) == str(other)
    assert not d.exists()
