# Runs the trading bot on Fly.io (Frankfurt) so it can reach Binance —
# GitHub Actions is US-based and Binance returns HTTP 451 there.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Blocking scheduler: runs one cycle immediately, then sync+trade every
# run_interval_hours (default 2h). Stays alive so Fly keeps the machine up.
CMD ["python", "-m", "app.cli", "run"]
