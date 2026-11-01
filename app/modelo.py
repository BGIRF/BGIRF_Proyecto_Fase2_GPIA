"""Carga y uso del modelo serializado.

El artefacto se entrena fuera de línea (src/entrenar_modelo.py) y aquí solo se
carga para inferencia, separando entrenamiento y operación (ISO/IEC 23053).
Antes de cargarlo se verifica su huella SHA-256 contra los metadatos: joblib usa
pickle, así que solo se carga un artefacto cuya integridad se comprobó.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import sklearn

log = logging.getLogger("claimcheck.modelo")


class ErrorIntegridad(RuntimeError):
    """El artefacto no coincide con la huella registrada en sus metadatos."""


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


class ServicioModelo:
    def __init__(self, ruta_modelo: Path, ruta_metadatos: Path, umbral: float | None = None):
        self.ruta_modelo = Path(ruta_modelo)
        self.ruta_metadatos = Path(ruta_metadatos)
        self._umbral_config = umbral
        self.pipeline = None
        self.metadatos: dict = {}
        self.clases: list[str] = []
        self.umbral: float = 0.5
        self.integridad_verificada = False
        self.advertencias: list[str] = []

    @property
    def cargado(self) -> bool:
        return self.pipeline is not None

    @property
    def version(self) -> str:
        return self.metadatos.get("version", "desconocida")

    def cargar(self) -> None:
        self.metadatos = json.loads(self.ruta_metadatos.read_text(encoding="utf-8"))
        esperado = self.metadatos["artefacto"]["sha256"]
        obtenido = sha256_archivo(self.ruta_modelo)
        if obtenido != esperado:
            raise ErrorIntegridad(
                f"SHA-256 del modelo no coincide (esperado {esperado[:12]}…, obtenido {obtenido[:12]}…). "
                "No se carga un artefacto alterado.")
        self.integridad_verificada = True

        version_entrenamiento = self.metadatos.get("entorno", {}).get("scikit_learn")
        if version_entrenamiento and version_entrenamiento != sklearn.__version__:
            aviso = (f"scikit-learn {sklearn.__version__} en ejecución y {version_entrenamiento} en entrenamiento: "
                     "fija la misma versión en requirements.txt.")
            self.advertencias.append(aviso)
            log.warning(aviso)

        self.pipeline = joblib.load(self.ruta_modelo)
        self.clases = [str(c) for c in self.pipeline.classes_]
        self.umbral = self._umbral_config if self._umbral_config is not None else float(
            self.metadatos["umbral_confianza"]["valor"])
        log.info("Modelo %s cargado (%s clases, τ=%.2f, SHA-256 verificado)",
                 self.version, len(self.clases), self.umbral)

    def predecir(self, textos: list[str]) -> list[dict]:
        if not self.cargado:
            raise RuntimeError("El modelo no está cargado")
        probabilidades = self.pipeline.predict_proba(textos)
        resultados = []
        for fila in probabilidades:
            i = int(np.argmax(fila))
            resultados.append({
                "categoria": self.clases[i],
                "confianza": round(float(fila[i]), 4),
                "probabilidades": {c: round(float(p), 4) for c, p in zip(self.clases, fila)},
            })
        return resultados
