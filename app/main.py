"""API REST de ClaimCheck IA (backend) y servidor del frontend.

Ejecutar en local:  uvicorn app.main:app --reload
Documentación interactiva (OpenAPI): http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.catalogo import AVISO_REVISOR, CATEGORIAS
from app.config import Config
from app.esquemas import (ClaimEntrada, EtiquetaEntrada, LoteEntrada, RespuestaEtiqueta, RespuestaLote,
                          ResultadoClaim, ResumenEtiqueta, Salud)
from app.modelo import ServicioModelo
from app.reglas import aplicar_regla, catalogo_reglas

log = logging.getLogger("claimcheck.api")

DESCRIPCION = """
Preclasificación de claims de etiquetado de alimentos para el organismo certificador ficticio
**CertiBajío, S.C.** (proyecto ClaimCheck IA).

* El **modelo** (TF-IDF + regresión logística) enruta cada claim a su checklist: NUTRIMENTAL, SALUD,
  AUSENCIA o MARKETING.
* El **motor de reglas** compara la tabla nutrimental contra los umbrales del Reg. (CE) 1924/2006.
* El **revisor técnico** decide: la API solo propone.
"""


def crear_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    logging.basicConfig(level=config.nivel_log,
                        format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    servicio = ServicioModelo(config.ruta_modelo, config.ruta_metadatos, config.umbral_confianza)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        servicio.cargar()  # si falla la integridad, el contenedor no arranca (fail fast)
        yield

    app = FastAPI(title="ClaimCheck IA · API", version=__version__, description=DESCRIPCION,
                  lifespan=ciclo_de_vida, openapi_tags=[
                      {"name": "Operación", "description": "Salud del servicio y metadatos del modelo"},
                      {"name": "Clasificación", "description": "Enrutamiento de claims y análisis de etiquetas"}])
    app.state.servicio = servicio
    app.state.config = config

    if config.origenes_permitidos:
        app.add_middleware(CORSMiddleware, allow_origins=config.origenes_permitidos,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def trazabilidad_y_limites(request: Request, call_next):
        id_solicitud = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        longitud = request.headers.get("content-length")
        if longitud and longitud.isdigit() and int(longitud) > config.tamano_maximo_bytes:
            return JSONResponse(status_code=413, headers={"X-Request-ID": id_solicitud}, content={
                "detail": f"El cuerpo de la solicitud supera {config.tamano_maximo_bytes} bytes."})
        inicio = time.perf_counter()
        respuesta = await call_next(request)
        ms = (time.perf_counter() - inicio) * 1000
        respuesta.headers["X-Request-ID"] = id_solicitud
        respuesta.headers["X-Tiempo-Proceso-ms"] = f"{ms:.2f}"
        if request.url.path.startswith("/api/"):
            log.info("%s %s %s %.1f ms id=%s", request.method, request.url.path,
                     respuesta.status_code, ms, id_solicitud)
        return respuesta

    # ── Lógica compartida ────────────────────────────────────────────────────────
    def resolver(textos: list[str], datos: dict | None) -> list[ResultadoClaim]:
        predicciones = servicio.predecir(textos)
        resultados = []
        for texto, pred in zip(textos, predicciones):
            categoria = pred["categoria"]
            regla = aplicar_regla(texto, datos)
            motivos = []
            if pred["confianza"] < servicio.umbral:
                motivos.append(f"Confianza {pred['confianza']:.2f} menor que el umbral τ = {servicio.umbral:.2f}.")
            if regla and categoria != "NUTRIMENTAL":
                motivos.append(f"La regla {regla['regla_id']} reconoce un claim nutrimental, "
                               f"pero el modelo propuso {categoria}.")
            resultados.append(ResultadoClaim(
                texto=texto, categoria=categoria, confianza=pred["confianza"],
                probabilidades=pred["probabilidades"], checklist=CATEGORIAS[categoria]["checklist"],
                referencia_normativa=CATEGORIAS[categoria]["referencia_normativa"],
                requiere_confirmacion=bool(motivos), motivos=motivos, regla=regla))
        return resultados

    # ── Operación ────────────────────────────────────────────────────────────────
    @app.get("/health", response_model=Salud, tags=["Operación"], summary="Verificación de salud (liveness)")
    def salud():
        return Salud(estado="ok", version_api=__version__, version_modelo=servicio.version,
                     modelo_cargado=servicio.cargado, integridad_verificada=servicio.integridad_verificada)

    @app.get("/api/v1/info", tags=["Operación"], summary="Metadatos y métricas del modelo desplegado")
    def info():
        m = servicio.metadatos
        return {
            "nombre": m.get("nombre"), "version_modelo": servicio.version, "version_api": __version__,
            "algoritmo": m.get("algoritmo"), "entrenado_en": m.get("fecha_entrenamiento"),
            "clases": servicio.clases, "umbral_confianza": servicio.umbral,
            "metricas_prueba": m.get("metricas_prueba", {}).get("globales"),
            "artefacto_sha256": m.get("artefacto", {}).get("sha256"),
            "advertencias": servicio.advertencias,
            "categorias": CATEGORIAS,
        }

    @app.get("/api/v1/reglas", tags=["Operación"], summary="Reglas deterministas disponibles")
    def reglas():
        return {"total": len(catalogo_reglas()), "reglas": catalogo_reglas()}

    # ── Clasificación ────────────────────────────────────────────────────────────
    @app.post("/api/v1/clasificar", response_model=ResultadoClaim, tags=["Clasificación"],
              summary="Clasifica un claim y lo enruta a su checklist")
    def clasificar(entrada: ClaimEntrada):
        return resolver([entrada.texto], None)[0]

    @app.post("/api/v1/clasificar/lote", response_model=RespuestaLote, tags=["Clasificación"],
              summary="Clasifica hasta 50 claims en una sola llamada")
    def clasificar_lote(entrada: LoteEntrada):
        resultados = resolver(entrada.claims, None)
        return RespuestaLote(modelo_version=servicio.version, umbral_confianza=servicio.umbral,
                             n_claims=len(resultados), resultados=resultados)

    @app.post("/api/v1/analizar-etiqueta", response_model=RespuestaEtiqueta, tags=["Clasificación"],
              summary="Analiza una etiqueta completa: enrutamiento + reglas nutrimentales")
    def analizar_etiqueta(entrada: EtiquetaEntrada):
        datos = entrada.datos_nutrimentales.model_dump() if entrada.datos_nutrimentales else None
        resultados = resolver(entrada.claims, datos)
        resumen = ResumenEtiqueta(
            total_claims=len(resultados),
            por_categoria=dict(Counter(r.categoria for r in resultados)),
            por_veredicto=dict(Counter(r.regla.veredicto_propuesto for r in resultados if r.regla)),
            claims_a_confirmar=sum(r.requiere_confirmacion for r in resultados))
        return RespuestaEtiqueta(producto=entrada.producto, modelo_version=servicio.version,
                                 umbral_confianza=servicio.umbral, resumen=resumen,
                                 resultados=resultados, aviso=AVISO_REVISOR)

    # ── Frontend (HTML + CSS + JavaScript que consume la API) ────────────────────
    if config.ruta_frontend.is_dir():
        app.mount("/static", StaticFiles(directory=config.ruta_frontend), name="static")

        @app.get("/", include_in_schema=False)
        def inicio():
            return FileResponse(config.ruta_frontend / "index.html")

    return app


app = crear_app()
