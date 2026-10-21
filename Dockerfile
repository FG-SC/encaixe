# Encaixe in one image: the FastAPI app serving the built front, SQLite and models on the /data volume.
# Production by default (ENCAIXE_ENV=prod): it refuses to start without BASE_URL (https) and SMTP. See docs/DEPLOY.md.

# --- front: Vite production build
FROM node:22-slim AS front
WORKDIR /front
COPY front/package.json front/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY front/ ./
RUN npm run build

# --- app
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Editable install: the code finds the front build, taxonomy and seed files relative to the repository root.
COPY pyproject.toml constraints.txt README.md LICENSE NOTICE ./
COPY app/ app/
RUN pip install -c constraints.txt -e .
COPY --from=front /front/dist front/dist

ENV ENCAIXE_ENV=prod \
    ENCAIXE_VAR_DIR=/data \
    HOME=/data \
    FORWARDED_ALLOW_IPS=*
RUN useradd --system --uid 10001 --home-dir /data encaixe && mkdir -p /data && chown encaixe /data
USER encaixe
VOLUME /data
EXPOSE 8000
# Generous start period: the first start downloads the embedding model (~250 MB) into /data/models.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status != 200)"
CMD ["encaixe", "serve", "--host", "0.0.0.0", "--port", "8000"]
