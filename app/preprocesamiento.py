"""Normalización de texto compartida por el entrenamiento y el servicio.

El vectorizador TF-IDF guarda una referencia a esta función dentro del artefacto
(.joblib). Por eso vive en el paquete `app`: el contenedor puede importarla al
cargar el modelo y el preprocesamiento es idéntico en desarrollo y en producción.
"""

import re
import unicodedata

_ESPACIOS = re.compile(r"\s+")


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin acentos (ñ → n) y con espacios colapsados.

    >>> normalizar_texto("  Sin AZÚCARES   añadidos ")
    'sin azucares anadidos'
    """
    texto = unicodedata.normalize("NFKD", str(texto).lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return _ESPACIOS.sub(" ", texto).strip()
