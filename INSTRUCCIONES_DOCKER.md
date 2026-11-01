# Instrucciones de ejecución del contenedor Docker

Guía para construir, ejecutar y verificar el contenedor de ClaimCheck IA en un equipo local.
Los comandos funcionan igual en PowerShell (Windows), Terminal (macOS) y Bash (Linux), salvo donde se indica.

## 1. Requisitos

| Requisito | Versión / detalle |
|---|---|
| Docker Desktop (Windows 10/11 con WSL 2, o macOS) | Reciente, con Docker Compose v2 incluido |
| Docker Engine (Linux) | 24 o superior, con el plugin `docker compose` |
| Git | Para clonar el repositorio (o descarga el ZIP desde GitHub) |
| Python 3.9+ | Solo para el script de validación; no necesita paquetes adicionales |
| Recursos | 2 GB libres en disco; el contenedor usa ~100 MB de RAM |
| Puerto | 8000 libre en el equipo |

Comprueba que Docker esté activo:

```bash
docker --version
docker compose version
docker info --format "{{.ServerVersion}}"
```

## 2. Obtener el código

```bash
git clone https://github.com/BGIRF/BGIRF_Proyecto_Fase2_GPIA.git
cd BGIRF_Proyecto_Fase2_GPIA
```

## 3. Construir la imagen

```bash
docker build -t claimcheck-api:1.0.0 .
```

El Dockerfile tiene tres etapas:

1. **base**: `python:3.12-slim` + dependencias fijadas en `requirements.txt`.
2. **test**: instala pytest y ejecuta las 84 pruebas. **Si una prueba falla, la construcción se detiene.**
3. **runtime**: imagen final con solo el código, el frontend y el modelo, ejecutada por un usuario sin privilegios.

En la salida debe aparecer una línea como `84 passed`. La primera construcción tarda unos minutos porque
descarga la imagen base y las dependencias; las siguientes reutilizan la caché.

Solo las pruebas, sin generar la imagen final:

```bash
docker build --target test -t claimcheck-api:test .
```

Comprobar la imagen:

```bash
docker images claimcheck-api
```

## 4. Ejecutar el contenedor

```bash
docker run -d --name claimcheck -p 8000:8000 claimcheck-api:1.0.0
```

Para probar con los mismos recursos del plan gratuito de Render:

```bash
docker run -d --name claimcheck -p 8000:8000 --memory 512m --cpus 0.1 claimcheck-api:1.0.0
```

| Variable de entorno | Valor por defecto | Para qué sirve |
|---|---|---|
| `PORT` | `8000` | Puerto interno; Render y Cloud Run lo asignan solos |
| `LOG_LEVEL` | `INFO` | Detalle de los logs |
| `UMBRAL_CONFIANZA` | el del entrenamiento (0.35) | Umbral τ para marcar claims a confirmar |
| `ORIGENES_PERMITIDOS` | vacío | Orígenes CORS, si el frontend se aloja en otro dominio |
| `WEB_CONCURRENCY` | `1` | Procesos de Uvicorn |

Ejemplo: `docker run -d --name claimcheck -p 8000:8000 -e LOG_LEVEL=DEBUG claimcheck-api:1.0.0`

### Alternativa con Docker Compose

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
docker compose down
```

`docker-compose.yml` ya limita el contenedor a 512 MB y 0.5 CPU. Para cambiar variables, copia `.env.example`
como `.env` y edítalo.

## 5. Verificar que funciona

**Estado del contenedor.** Tras unos segundos, `STATUS` debe decir `(healthy)`:

```bash
docker ps
docker logs claimcheck
```

En los logs debe aparecer: `Modelo 1.0.0 cargado (4 clases, τ=0.35, SHA-256 verificado)`.

**En el navegador:**

- http://localhost:8000 → frontend. Presiona **Cargar ejemplo** y luego **Analizar etiqueta**.
- http://localhost:8000/docs → documentación interactiva (Swagger UI); ahí puedes probar cada endpoint con *Try it out*.

**Desde la terminal.** PowerShell (Windows):

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/clasificar `
  -ContentType "application/json; charset=utf-8" -Body '{"texto": "Sin gluten"}'
```

Bash / Terminal (macOS, Linux, Git Bash):

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/v1/clasificar -H "Content-Type: application/json" -d '{"texto": "Sin gluten"}'
```

**Validación completa (50 pruebas de punta a punta):**

```bash
python scripts/validar_contenedor.py
```

Termina con `Resultado: 50/50 pruebas aprobadas` y guarda el detalle en `resultados/validacion_local.json`.
En Windows, si `python` no existe, usa `py scripts/validar_contenedor.py`.

## 6. Detener y limpiar

```bash
docker stop claimcheck
docker rm claimcheck
docker rmi claimcheck-api:1.0.0      # opcional: borra la imagen
```

## 7. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Cannot connect to the Docker daemon` / `error during connect` | Docker Desktop no está abierto | Abre Docker Desktop y espera a que diga *Engine running* |
| `port is already allocated` | El puerto 8000 está ocupado | Usa otro puerto local: `-p 8080:8000` y abre http://localhost:8080 |
| `Conflict. The container name "/claimcheck" is already in use` | Ya existe un contenedor con ese nombre | `docker rm -f claimcheck` y vuelve a ejecutar |
| El build se detiene en la etapa `test` | Una prueba falló | Lee el nombre de la prueba en la salida; la imagen no se genera hasta corregirla |
| El contenedor se detiene al arrancar con `ErrorIntegridad` | El archivo `.joblib` no coincide con su SHA-256 | Vuelve a descargar `modelos/` o reentrena con `python -m src.entrenar_modelo` |
| `STATUS` se queda en `(health: starting)` | El servicio aún carga el modelo (más lento con poca CPU) | Espera 20–30 s; revisa `docker logs claimcheck` |
| En Windows, `scripts\validar_contenedor.py` falla con caracteres raros | Consola sin UTF-8 | Ejecuta `chcp 65001` antes del script o usa Windows Terminal |
| WSL 2 no instalado (Windows) | Docker Desktop lo requiere | `wsl --install` en PowerShell como administrador y reinicia |
