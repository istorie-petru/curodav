# Same Radicale the systemd deploy uses (deploy/radicale/install-radicale.sh
# pip-installs it into its own venv) -- containerized instead of a venv, no
# third-party Radicale image whose internals this repo doesn't control.
FROM python:3.12-slim

RUN pip install --no-cache-dir "radicale>=3.3" bcrypt

EXPOSE 5232
ENTRYPOINT ["python", "-m", "radicale"]
CMD ["--config", "/etc/radicale/config"]
