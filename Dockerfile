# syntax=docker/dockerfile:1
FROM node:22.11.0-slim AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.12.8-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CLAIMTRACE_DB=/data/claimtrace.db CLAIMTRACE_HOST=0.0.0.0 CLAIMTRACE_CONTAINER_MODE=true
WORKDIR /app
COPY pyproject.toml README.md requirements.lock ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY examples ./examples
COPY evals ./evals
COPY --from=web /src/apps/api/static ./apps/api/static
RUN pip install --require-hashes -r requirements.lock && pip install --no-deps . && useradd --uid 10001 --create-home claimtrace && mkdir -p /data && chown claimtrace /data
USER claimtrace
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["claimtrace", "serve", "--host", "0.0.0.0", "--port", "8000"]
