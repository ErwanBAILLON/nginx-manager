"""Strict validation of every user-supplied value that ends up in an nginx config.

All functions return the normalised value or raise ``ValidationError``.
Nothing is ever "sanitised" silently: an invalid value is rejected.
"""

from __future__ import annotations

import ipaddress
import re

from .errors import ValidationError

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
DOMAIN_RE = re.compile(rf"^(?:\*\.)?(?:{_LABEL}\.)+[a-z]{{2,63}}$")
HOSTNAME_RE = re.compile(rf"^(?:{_LABEL}\.)*{_LABEL}$")
SITE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
DIRECTIVE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RATE_RE = re.compile(r"^[1-9][0-9]{0,5}r/[sm]$")
INDEX_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
EMAIL_RE = re.compile(r"^[^@\s]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
URL_PATH_RE = re.compile(r"^/[A-Za-z0-9/._~-]*$")
FORBIDDEN_IN_VALUE = set(";{}\n\r\0")
FORBIDDEN_IN_PATH = set(" \t;{}\"'\n\r\0$`\\")

# Directives that would let a generated site reach outside its own block.
BLOCKED_DIRECTIVES = frozenset({"include", "load_module", "lua_code_cache", "perl"})


def domain(value: str) -> str:
    """A DNS name (optionally a ``*.`` wildcard), lower-cased. ``localhost`` is accepted."""
    v = value.strip().lower().rstrip(".")
    if v == "localhost":
        return v
    if len(v) > 253 or not DOMAIN_RE.match(v):
        raise ValidationError(f"invalid domain name: {value!r}")
    return v


def site_name(value: str) -> str:
    """A config file name (without ``.conf``), safe for use as a path component."""
    v = value.strip()
    if v.endswith(".conf"):
        v = v[: -len(".conf")]
    v = v.replace("*", "_wildcard")
    if not v or ".." in v or not SITE_NAME_RE.match(v):
        raise ValidationError(f"invalid site name: {value!r}")
    return v


def domain_to_name(dom: str) -> str:
    """File name used for a domain: ``*.example.com`` -> ``_wildcard.example.com``."""
    return site_name(dom)


def port(value: str | int) -> int:
    try:
        p = int(str(value).strip())
    except ValueError as exc:
        raise ValidationError(f"invalid port: {value!r}") from exc
    if not 1 <= p <= 65535:
        raise ValidationError(f"port out of range 1-65535: {p}")
    return p


def absolute_path(value: str) -> str:
    """An absolute filesystem path without shell/nginx metacharacters or ``..`` segments."""
    v = value.strip()
    if not v.startswith("/"):
        raise ValidationError(f"path must be absolute: {value!r}")
    if any(c in FORBIDDEN_IN_PATH for c in v):
        raise ValidationError(f"path contains forbidden characters: {value!r}")
    if any(seg == ".." for seg in v.split("/")):
        raise ValidationError(f"path must not contain '..': {value!r}")
    return v.rstrip("/") or "/"


def url_path(value: str) -> str:
    """A location prefix such as ``/`` or ``/api/v1``."""
    v = value.strip()
    if not URL_PATH_RE.match(v) or "//" in v or "/../" in f"{v}/":
        raise ValidationError(f"invalid location path: {value!r}")
    return v


def _host(value: str) -> str:
    if value.startswith("[") and value.endswith("]"):
        try:
            ipaddress.IPv6Address(value[1:-1])
        except ValueError as exc:
            raise ValidationError(f"invalid IPv6 host: {value!r}") from exc
        return value
    try:
        ipaddress.IPv4Address(value)
        return value
    except ValueError:
        pass
    if HOSTNAME_RE.match(value.lower()) and not all(lbl.isdigit() for lbl in value.split(".")):
        return value.lower()
    raise ValidationError(f"invalid host: {value!r}")


def upstream(value: str) -> str:
    """``http(s)://host[:port][/path]`` for ``proxy_pass``."""
    v = value.strip()
    m = re.match(r"^(https?)://([^/:\s]+|\[[0-9a-fA-F:]+\])(?::(\d{1,5}))?(/[^\s;{}\"'$`]*)?$", v)
    if not m:
        raise ValidationError(f"invalid upstream URL (expected http(s)://host[:port]): {value!r}")
    scheme, host, prt, path = m.groups()
    host = _host(host)
    if prt is not None:
        port(prt)
    return f"{scheme}://{host}" + (f":{prt}" if prt else "") + (path or "")


def directive_name(value: str) -> str:
    v = value.strip()
    if not DIRECTIVE_NAME_RE.match(v):
        raise ValidationError(f"invalid directive name: {value!r}")
    if v in BLOCKED_DIRECTIVES:
        raise ValidationError(f"directive not allowed in custom locations: {v}")
    return v


def directive_value(value: str) -> str:
    v = value.strip()
    if not v or any(c in FORBIDDEN_IN_VALUE for c in v):
        raise ValidationError(
            f"directive value must not be empty or contain ; {{ }} newline: {value!r}"
        )
    if v.count('"') % 2 or v.count("'") % 2:
        raise ValidationError(f"unbalanced quotes in directive value: {value!r}")
    return v


def location_arg(value: str) -> tuple[str, str, str]:
    """Parse ``PATH:DIRECTIVE=VALUE`` as used by ``--location``."""
    if ":" not in value or "=" not in value.split(":", 1)[1]:
        raise ValidationError(f"expected PATH:DIRECTIVE=VALUE, got {value!r}")
    path, rest = value.split(":", 1)
    name, val = rest.split("=", 1)
    return url_path(path), directive_name(name), directive_value(val)


def rate(value: str) -> str:
    v = value.strip().lower()
    if not RATE_RE.match(v):
        raise ValidationError(f"invalid rate (expected e.g. 10r/s or 60r/m): {value!r}")
    return v


def index_files(value: str) -> str:
    tokens = value.split()
    if not tokens or not all(INDEX_TOKEN_RE.match(t) for t in tokens):
        raise ValidationError(f"invalid index file list: {value!r}")
    return " ".join(tokens)


def email(value: str) -> str:
    v = value.strip()
    if not EMAIL_RE.match(v):
        raise ValidationError(f"invalid email address: {value!r}")
    return v


def csp(value: str) -> str:
    """A Content-Security-Policy value. ``;`` is legitimate here, quotes/newlines/braces are not."""
    v = value.strip()
    if not v or any(c in '"{}\n\r\0$' for c in v):
        raise ValidationError(f"invalid CSP value: {value!r}")
    return v


def resolver(value: str) -> str:
    """An IPv4/IPv6 address for the ``resolver`` directive (IPv6 gets bracketed)."""
    v = value.strip()
    try:
        ip = ipaddress.ip_address(v.strip("[]"))
    except ValueError as exc:
        raise ValidationError(f"invalid resolver address: {value!r}") from exc
    return f"[{ip}]" if ip.version == 6 else str(ip)
