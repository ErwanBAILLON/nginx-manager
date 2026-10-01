"""The declarative description of a site. Validated once, rendered by ``templates``."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from . import validators as v
from .errors import ValidationError


@dataclass
class Location:
    path: str
    directives: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class SiteSpec:
    domain: str
    mode: str = "proxy"  # "proxy" | "static"
    aliases: list[str] = field(default_factory=list)
    port: int = 80
    ipv6: bool = False
    # proxy
    proxy_url: str | None = None
    proxy_path: str = "/"
    websocket: bool = True
    # static
    root: str | None = None
    index: str = "index.html"
    # tls
    ssl: bool = False
    ssl_port: int = 443
    cert: str | None = None
    key: str | None = None
    redirect_http: bool = False
    hsts: bool = False
    resolvers: list[str] = field(default_factory=list)
    # headers
    csp: str | None = None
    # rate limiting (opt-in)
    rate_limit: str | None = None
    rate_burst: int = 20
    locations: list[Location] = field(default_factory=list)

    # ----------------------------------------------------------------- derived
    @property
    def name(self) -> str:
        return v.domain_to_name(self.domain)

    @property
    def server_names(self) -> list[str]:
        return [self.domain, *self.aliases]

    @property
    def zone(self) -> str:
        return "nm_" + re.sub(r"[^A-Za-z0-9_]", "_", self.name)

    # --------------------------------------------------------------- validate
    def validate(self) -> SiteSpec:
        """Normalise every field in place and raise ``ValidationError`` on the first problem."""
        self.domain = v.domain(self.domain)
        self.aliases = [v.domain(a) for a in self.aliases]
        if self.mode not in ("proxy", "static"):
            raise ValidationError(f"mode must be 'proxy' or 'static', got {self.mode!r}")
        self.port = v.port(self.port)
        self.ssl_port = v.port(self.ssl_port)
        if self.ssl and self.port == self.ssl_port:
            raise ValidationError("--port and --ssl-port must differ")
        if self.mode == "proxy":
            if not self.proxy_url:
                raise ValidationError("proxy mode requires an upstream URL (--proxy)")
            self.proxy_url = v.upstream(self.proxy_url)
            self.proxy_path = v.url_path(self.proxy_path)
        else:
            if not self.root:
                raise ValidationError("static mode requires a root directory (--static)")
            self.root = v.absolute_path(self.root)
            self.index = v.index_files(self.index)
        if self.cert is not None:
            self.cert = v.absolute_path(self.cert)
        if self.key is not None:
            self.key = v.absolute_path(self.key)
        if (self.cert is None) != (self.key is None):
            raise ValidationError("--cert and --key must be given together")
        if not self.ssl and (self.redirect_http or self.hsts or self.cert):
            raise ValidationError("--redirect-http, --hsts and --cert/--key require --ssl")
        if self.csp is not None:
            self.csp = v.csp(self.csp)
        if self.rate_limit is not None:
            self.rate_limit = v.rate(self.rate_limit)
            if not 1 <= self.rate_burst <= 10000:
                raise ValidationError("rate burst must be between 1 and 10000")
        self.resolvers = [v.resolver(r) for r in self.resolvers]
        seen: set[str] = set()
        for loc in self.locations:
            loc.path = v.url_path(loc.path)
            if loc.path in seen or (self.mode == "proxy" and loc.path == self.proxy_path):
                raise ValidationError(f"duplicate location path: {loc.path}")
            seen.add(loc.path)
            if not loc.directives:
                raise ValidationError(f"location {loc.path} has no directives")
            loc.directives = [
                (v.directive_name(n), v.directive_value(val)) for n, val in loc.directives
            ]
        return self

    # ------------------------------------------------------------ (de)serialise
    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteSpec:
        locs = [
            Location(path=loc["path"], directives=[tuple(d) for d in loc["directives"]])
            for loc in data.get("locations", [])
        ]
        kwargs = {k: val for k, val in data.items() if k != "locations"}
        return cls(locations=locs, **kwargs)

    @classmethod
    def from_json(cls, text: str) -> SiteSpec:
        return cls.from_dict(json.loads(text))
