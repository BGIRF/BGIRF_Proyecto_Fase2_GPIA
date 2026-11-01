"""Configuración del servicio a partir de variables de entorno (12-factor).

Ninguna configuración se escribe en el código: el mismo contenedor corre en local,
en Render o en Cloud Run cambiando solo las variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ruta(variable: str, por_defecto: str) -> Path:
    ruta = Path(os.getenv(variable, por_defecto))
    return ruta if ruta.is_absolute() else RAIZ / ruta


def _float_opcional(variable: str) -> float | None:
    valor = os.getenv(variable, "").strip()
    if not valor:
        return None
    numero = float(valor)
    if not 0 <= numero <= 1:
        raise ValueError(f"{variable} debe estar entre 0 y 1; se recibió {numero}")
    return numero


@dataclass(frozen=True)
class Config:
    ruta_modelo: Path = field(default_factory=lambda: _ruta("MODELO_PATH", "modelos/claimcheck_router_v1.joblib"))
    ruta_metadatos: Path = field(default_factory=lambda: _ruta("METADATOS_PATH", "modelos/claimcheck_router_v1.json"))
    ruta_frontend: Path = field(default_factory=lambda: _ruta("FRONTEND_DIR", "frontend"))
    # Si se deja vacío se usa el umbral τ elegido en el entrenamiento (metadatos del modelo).
    umbral_confianza: float | None = field(default_factory=lambda: _float_opcional("UMBRAL_CONFIANZA"))
    # Orígenes CORS separados por coma; vacío = solo el mismo origen (el frontend lo sirve la propia API).
    origenes_permitidos: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("ORIGENES_PERMITIDOS", "").split(",") if o.strip()])
    tamano_maximo_bytes: int = field(default_factory=lambda: int(os.getenv("TAMANO_MAXIMO_BYTES", "65536")))
    nivel_log: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


MAX_CLAIMS_LOTE = 50
MAX_CLAIMS_ETIQUETA = 30
LONGITUD_MIN_CLAIM = 2
LONGITUD_MAX_CLAIM = 300
