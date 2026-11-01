# ─────────────────────────────────────────────────────────────────────────────
# ClaimCheck IA · API (FastAPI) + frontend + modelo en un solo contenedor
#
#   docker build -t claimcheck-api:1.0.0 .                # imagen de ejecución
#   docker build --target test -t claimcheck-api:test .   # solo la etapa de pruebas
#   docker run -d --name claimcheck -p 8000:8000 claimcheck-api:1.0.0
#
# Tres etapas:
#   base    → Python + dependencias fijadas (requirements.txt)
#   test    → instala pytest y corre las 84 pruebas; si una falla, el build falla
#   runtime → imagen final: solo código, frontend y modelo; usuario sin privilegios
# ─────────────────────────────────────────────────────────────────────────────
ARG PYTHON_VERSION=3.12

# ── Etapa 1: base con las dependencias de ejecución ─────────────────────────
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /srv/claimcheck
# Se copia primero solo requirements.txt para aprovechar la caché de capas:
# si cambia el código pero no las dependencias, este paso no se repite.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Etapa 2: pruebas automatizadas (no llega a la imagen final) ─────────────
FROM base AS test
COPY requirements-dev.txt pytest.ini ./
RUN pip install -r requirements-dev.txt
COPY app/ app/
COPY frontend/ frontend/
COPY modelos/ modelos/
COPY data/ data/
COPY tests/ tests/
RUN python -m pytest -q && touch /tmp/pruebas_superadas

# ── Etapa 3: imagen de ejecución ────────────────────────────────────────────
FROM base AS runtime
LABEL org.opencontainers.image.title="ClaimCheck IA API" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.description="Preclasificación de claims de etiquetado de alimentos (FastAPI + scikit-learn)" \
      org.opencontainers.image.authors="Brandon Gilberto Imanol Retana Fuentes" \
      org.opencontainers.image.source="https://github.com/BGIRF/BGIRF_Proyecto_Fase2_GPIA"

# Compuerta de calidad: esta línea obliga a construir la etapa "test",
# así que la imagen final solo existe si todas las pruebas pasaron.
COPY --from=test /tmp/pruebas_superadas /srv/claimcheck/.pruebas_superadas

# Usuario sin privilegios. El código y el modelo quedan como propiedad de root
# (solo lectura para la app): el proceso no puede modificarlos.
RUN useradd --create-home --uid 10001 claimcheck
COPY app/ app/
COPY frontend/ frontend/
COPY modelos/ modelos/
USER claimcheck

# PORT lo sobrescribe la plataforma (Render usa 10000 y Cloud Run 8080).
ENV PORT=8000 \
    WEB_CONCURRENCY=1 \
    LOG_LEVEL=INFO
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
