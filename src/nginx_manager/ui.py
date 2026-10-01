"""Plain-text output helpers. Colour only when stdout is a TTY (and NO_COLOR is unset)."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

_COLORS = {"green": "32", "yellow": "33", "red": "31", "dim": "2", "bold": "1"}


def use_color(stream: object = None) -> bool:
    stream = stream or sys.stdout
    isatty = getattr(stream, "isatty", lambda: False)
    return bool(isatty()) and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def paint(text: str, color: str) -> str:
    if not use_color():
        return text
    return f"\033[{_COLORS[color]}m{text}\033[0m"


def info(msg: str) -> None:
    print(msg)


def ok(msg: str) -> None:
    print(paint("ok   ", "green") + msg)


def warn(msg: str) -> None:
    print(paint("warn ", "yellow") + msg, file=sys.stderr)


def error(msg: str) -> None:
    print(paint("error", "red") + " " + msg, file=sys.stderr)


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers).rstrip(), fmt.format(*("-" * w for w in widths))]
    lines += [fmt.format(*row).rstrip() for row in rows]
    return "\n".join(lines)


def confirm(question: str, default: bool = False, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise SystemExit(f"{question} -> refusing to guess without a TTY; pass --yes")
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("please answer y or n")
