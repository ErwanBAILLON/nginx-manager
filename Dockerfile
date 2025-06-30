FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    nginx certbot \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip3 install --no-cache-dir -r requirements.txt

# Remove default site
RUN rm -f /etc/nginx/sites-enabled/default

VOLUME ["/etc/nginx/sites-available", "/etc/nginx/sites-enabled", "/var/log/nginx"]

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "main.py"]
