# Two-stage image: Node builds the Vite bundle, the runtime is standard-library Python only.

FROM node:22-slim AS frontend
WORKDIR /build/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run typecheck && npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 fpl
WORKDIR /app
COPY --chown=fpl:fpl dashboard.py fetch_fpl.py config.json digest.md ./
COPY --chown=fpl:fpl fpl_brief/ ./fpl_brief/
COPY --chown=fpl:fpl data/ ./data/
COPY --from=frontend --chown=fpl:fpl /build/dashboard/dist/ ./dashboard/dist/
RUN chown fpl:fpl /app
USER fpl
# Railway injects PORT; dashboard.py binds 0.0.0.0 when PORT is set.
CMD ["python", "dashboard.py"]
