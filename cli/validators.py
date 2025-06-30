import re

def validate_domain(domain: str) -> bool:
    """
    Validate domain name format.
    
    Args:
        domain: Domain name to validate
        
    Returns:
        True if domain is valid, False otherwise
    """
    if not domain:
        return False
        
    pattern = r'^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(pattern, domain))

def validate_port(port: str) -> bool:
    """
    Validate port number.
    
    Args:
        port: Port number as string
        
    Returns:
        True if port is valid, False otherwise
    """
    try:
        port_num = int(port)
        return 1 <= port_num <= 65535
    except ValueError:
        return False

def validate_path(path: str) -> bool:
    """
    Validate URL path.
    
    Args:
        path: URL path
        
    Returns:
        True if path is valid, False otherwise
    """
    # Path must start with /
    if not path or not path.startswith('/'):
        return False
    return True

def sanitize_input(input_str: str) -> str:
    """
    Sanitize user input to prevent command injection.
    
    Args:
        input_str: Input string to sanitize
        
    Returns:
        Sanitized string
    """
    # Remove potentially dangerous shell characters
    return re.sub(r'[;&|<>$`]', '', input_str)
