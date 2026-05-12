# microservice/Dockerfile

# ── Stage 1: builder ────────────────────────────────────────────────────────
# Por qué multi-stage build:
#   - El stage builder instala todo lo necesario para compilar
#   - El stage final solo copia lo necesario para correr
#   - La imagen final es más pequeña y tiene menos superficie de ataque
#   - Trivy va a escanear la imagen final — menos paquetes = menos CVEs

FROM python:3.12-slim AS builder

# Crear usuario no-root desde el builder
# Por qué: correr como root en contenedor es un hallazgo de seguridad
# que Trivy y ZAP reportarán
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copiar solo requirements primero
# Por qué: Docker cachea layers. Si el código cambia pero las deps no,
# esta layer se reutiliza — builds más rápidos en CI
COPY requirements.txt .

# Instalar dependencias en directorio específico
# --no-cache-dir: no guardar cache de pip en la imagen
# --prefix: instalar en /install para copiar limpio al stage final
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Metadata de la imagen — OCI standard labels
# Permite trazabilidad: de qué repo viene, qué commit, qué versión
ARG APP_VERSION=0.1.0
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/ivanmunozm/mcp-devsecops-lab"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL org.opencontainers.image.description="ms-devsecops laboratorio"

# Recrear usuario en el stage final
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copiar dependencias instaladas desde el builder
COPY --from=builder /install /usr/local

# Copiar el código de la aplicación
COPY app.py .

# Cambiar al usuario no-root ANTES de definir CMD
# Si esto va después, el proceso corre como root hasta el USER
USER appuser

# Variables de entorno con defaults seguros
ENV PORT=8080
ENV ENVIRONMENT=production
ENV APP_VERSION=${APP_VERSION}

# Exponer el puerto documentalmente
# No abre el puerto — eso lo hace docker run -p o Kubernetes
EXPOSE 8080

# HEALTHCHECK para que Docker (y Kubernetes) detecten si el contenedor está sano
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# CMD vs ENTRYPOINT:
# CMD: puede ser sobreescrito en docker run — flexible para testing
# ENTRYPOINT: no se sobreescribe fácilmente — para binarios dedicados
# Para un servicio web, CMD es la elección correcta
CMD ["python", "app.py"]