FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium \
    && useradd --uid 10001 --create-home kitchen
COPY *.py ./
COPY vendor ./vendor
COPY scripts ./scripts
COPY web ./web
RUN mkdir -p /app/.data /app/data && chown -R kitchen:kitchen /app/.data /app/data
USER kitchen
EXPOSE 8767
CMD ["python", "server.py"]
