import pytest

from nginx_manager import validators as v
from nginx_manager.errors import ValidationError


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Example.COM", "example.com"),
        ("*.example.com", "*.example.com"),
        ("localhost", "localhost"),
        ("a.b.co.uk.", "a.b.co.uk"),
    ],
)
def test_domain_ok(value: str, expected: str) -> None:
    assert v.domain(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example",
        "-bad.com",
        "exa mple.com",
        "ex;ample.com",
        "a..b.com",
        "x" * 260,
        "*.*.com",
        "foo.com/bar",
        "$host.com",
    ],
)
def test_domain_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        v.domain(value)


def test_site_name() -> None:
    assert v.site_name("app.example.com.conf") == "app.example.com"
    assert v.site_name("*.example.com") == "_wildcard.example.com"
    for bad in ("", "../etc", "a/b", ".hidden", "a;b"):
        with pytest.raises(ValidationError):
            v.site_name(bad)


def test_port() -> None:
    assert v.port("8080") == 8080
    for bad in ("0", "65536", "abc", "-1"):
        with pytest.raises(ValidationError):
            v.port(bad)


def test_absolute_path() -> None:
    assert v.absolute_path("/var/www/site/") == "/var/www/site"
    assert v.absolute_path("/") == "/"
    for bad in ("var/www", "/var/../etc", "/var/w ww", "/a;b", "/a{b}", "/a$b", "/a\\b"):
        with pytest.raises(ValidationError):
            v.absolute_path(bad)


def test_url_path() -> None:
    assert v.url_path("/api/v1") == "/api/v1"
    for bad in ("api", "/a b", "/a;b", "//x", "/a/../b", "/x{", "/é"):
        with pytest.raises(ValidationError):
            v.url_path(bad)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://Backend.Internal", "https://backend.internal"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://[::1]:8080/api", "http://[::1]:8080/api"),
    ],
)
def test_upstream_ok(value: str, expected: str) -> None:
    assert v.upstream(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "localhost:3000",
        "ftp://x",
        "http://",
        "http://host:99999",
        "http://ho st",
        "http://host;rm",
        "http://host/{",
        "http://[zz]",
        "http://999.1.1.1",
    ],
)
def test_upstream_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        v.upstream(value)


def test_directives() -> None:
    assert v.directive_name("proxy_pass") == "proxy_pass"
    assert v.directive_value(" 10m ") == "10m"
    assert v.directive_value('"a b"') == '"a b"'
    for bad in ("Proxy_Pass", "proxy-pass", "1x", "", "include"):
        with pytest.raises(ValidationError):
            v.directive_name(bad)
    for bad in ("", "a;b", "a{", "}", "a\nb", '"unbalanced'):
        with pytest.raises(ValidationError):
            v.directive_value(bad)


def test_location_arg() -> None:
    assert v.location_arg("/api:proxy_pass=http://x:1") == ("/api", "proxy_pass", "http://x:1")
    assert v.location_arg("/s:proxy_set_header=Host $host") == (
        "/s",
        "proxy_set_header",
        "Host $host",
    )
    for bad in ("/api", "/api:proxy_pass", "api:x=y", "/a:x=a;b"):
        with pytest.raises(ValidationError):
            v.location_arg(bad)


def test_misc() -> None:
    assert v.rate("10R/S") == "10r/s"
    assert v.rate("60r/m") == "60r/m"
    assert v.index_files(" index.html  index.htm ") == "index.html index.htm"
    assert v.email("ops@example.com") == "ops@example.com"
    assert v.csp("default-src 'self'; img-src data:") == "default-src 'self'; img-src data:"
    assert v.resolver("::1") == "[::1]"
    assert v.resolver("[2001:db8::1]") == "[2001:db8::1]"
    assert v.resolver("1.1.1.1") == "1.1.1.1"
    for fn, bad in (
        (v.rate, "10"),
        (v.rate, "0r/s"),
        (v.rate, "1r/h"),
        (v.index_files, ""),
        (v.index_files, "a;b"),
        (v.email, "nope"),
        (v.email, "a@b"),
        (v.csp, ""),
        (v.csp, 'x"y'),
        (v.csp, "a}b"),
        (v.resolver, "dns.google"),
        (v.resolver, "1.2.3"),
    ):
        with pytest.raises(ValidationError):
            fn(bad)
