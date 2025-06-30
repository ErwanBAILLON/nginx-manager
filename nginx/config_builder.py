from typing import List, Dict, Tuple, Any, Optional
from pathlib import Path

from nginx.templates import (
    SERVER_BLOCK_TEMPLATE, 
    REDIRECT_SERVER_BLOCK, 
    PROXY_LOCATION_BLOCK,
    STATIC_SERVER_DIRECTIVES,
    SECURITY_HEADERS,
    SSL_CONFIG_BLOCK,
    RATE_LIMITING,
    LOG_FORMAT_MAIN
)

class NginxConfigBuilder:
    """Builds Nginx configuration files based on predefined templates and security best practices."""

    def __init__(self):
        # Define ssl template directives
        self.ssl_block = SSL_CONFIG_BLOCK
        self.security_headers = SECURITY_HEADERS
        self.rate_limiting = RATE_LIMITING
        self.log_format = LOG_FORMAT_MAIN
        
    def build(self, domain: str, cfg: Dict[str, Any], locations: List[Dict[str, Any]], 
              ssl: bool = False, redirect: bool = False) -> str:
        """
        Build a complete Nginx server configuration.
        
        Args:
            domain: Domain name
            cfg: Configuration dictionary
            locations: List of location blocks
            ssl: Whether to include SSL configuration
            redirect: Whether this is a redirect block
            
        Returns:
            Complete Nginx server configuration as a string
        """
        if redirect:
            return REDIRECT_SERVER_BLOCK.format(domain=domain)
        
        location_blocks = []
        if cfg['mode'] == 'proxy':
            location_blocks.append(self._build_proxy_location(cfg['path'], cfg['proxy_pass']))
        
        for loc in locations:
            location_blocks.append(self._build_custom_location(loc['path'], loc['directives']))
        
        log_config = self._build_log_config(domain)
        security_config = self._build_security_config()
        ssl_config = self._build_ssl_config(domain) if ssl else ""
        rate_limiting = "\n    ".join(self.rate_limiting)
        
        server_params = {
            "domain": domain,
            "port": cfg['listen'],
            "locations": "\n\n".join(location_blocks),
            "ssl_config": ssl_config,
            "security_headers": security_config,
            "log_config": log_config,
            "rate_limiting": rate_limiting
        }
        
        if cfg['mode'] == 'static':
            root_dir = cfg['root']
            index_files = cfg['index']
            static_directives = STATIC_SERVER_DIRECTIVES.format(
                root=root_dir,
                index=index_files
            )
            server_params["static_directives"] = static_directives
        else:
            server_params["static_directives"] = ""
        
        config = self.log_format + "\n" + SERVER_BLOCK_TEMPLATE.format(**server_params)
        return config

    def _build_proxy_location(self, path: str, proxy_pass: str) -> str:
        """Build a proxy location block."""
        return PROXY_LOCATION_BLOCK.format(path=path, proxy_pass=proxy_pass)
        
    def _build_custom_location(self, path: str, directives: List[Tuple[str, str]]) -> str:
        """Build a custom location block with directives."""
        lines = [f"location {path} {{"]
        for directive, value in directives:
            lines.append(f"    {directive} {value};")
        lines.append("}")
        return "\n".join(lines)
        
    def _build_log_config(self, domain: str) -> str:
        """Build logging configuration for a domain."""
        return f"""
    # Logging configuration
    access_log /var/log/nginx/{domain}/access.log main buffer=16k;
    error_log /var/log/nginx/{domain}/error.log warn;
    """
        
    def _build_security_config(self) -> str:
        """Build security headers configuration."""
        return "\n    ".join(self.security_headers)
        
    def _build_ssl_config(self, domain: str) -> str:
        """Build SSL configuration for a domain."""
        ssl_lines = []
        for directive, template in self.ssl_block:
            value = template.format(domain=domain)
            if directive in ("include", "ssl_dhparam") and not Path(value).exists():
                continue
            ssl_lines.append(f"{directive} {value};")
        
        return "\n    ".join(ssl_lines)
