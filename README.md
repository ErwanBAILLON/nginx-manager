# Nginx Manager

An interactive command-line tool for creating, managing, and deploying Nginx configurations with ease.

## Overview

Nginx Manager simplifies the process of creating and managing Nginx server configurations through an interactive CLI interface. It handles common configuration patterns, generates syntax-correct configs, and integrates with Certbot for SSL certificate management.

## Features

- 🚀 **Interactive CLI**: Guided prompts for all configuration options
- 📋 **List Existing Configs**: Quick overview of all configurations with domain, port, type and SSL status
- ✨ **Create New Configs**: Generate configurations for static sites or proxied applications
- 🔍 **View Config Details**: See full configuration files without leaving the tool
- 🗑️ **Delete Configs**: Clean up configurations safely
- 🔒 **SSL Integration**: Built-in Certbot integration for SSL certificate provisioning
- 🧩 **Modular Design**: Object-oriented code structure for easy maintenance

## Requirements

- Python 3.6+ (uses f-strings)
- Nginx
- Certbot (optional, for SSL)
- Root privileges (sudo)

## Installation

1. Clone this repository:
   ```bash
   git clone git@github.com:ErwanBAILLON/nginx-manager.git
   cd nginx-manager
   ```

2. Make the script executable:
   ```bash
   chmod +x main.py
   ```

## Usage

Run the script as root (required to modify Nginx configurations):

```bash
sudo ./main.py
```

### Main Menu

The tool presents a menu with the following options:

1. **List configs** - Shows all existing Nginx configurations
2. **Create config** - Create a new Nginx configuration
3. **Show config details** - View the contents of an existing config
4. **Delete config** - Remove a configuration
5. **Quit** - Exit the application

### Creating a Configuration

When creating a new configuration, you'll be prompted for:

- Domain name
- Port (default: 80)
- Mode: proxy (for applications) or static (for file serving)
- For proxy: path and upstream URL
- For static: root directory and index files
- Additional location blocks
- SSL options with Certbot integration

## Examples

### Proxy Configuration Example

```
server {
    listen 80;
    server_name example.com;
    
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        # ... other proxy headers
    }
    
    # SSL configuration added by Certbot
}
```

### Static Site Configuration Example

```
server {
    listen 80;
    server_name example.com;
    root /var/www/html/example;
    index index.html;
    
    # SSL configuration added by Certbot
}
```

## License

GNU General Public License v3.0

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
