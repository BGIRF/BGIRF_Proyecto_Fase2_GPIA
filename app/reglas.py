"""Motor de reglas deterministas para claims nutrimentales.

En ClaimCheck IA los cálculos numéricos no los hace el modelo: los hace una regla
fija que siempre da el mismo resultado. El modelo enruta el claim; la regla
compara la tabla nutrimental contra el umbral; el revisor técnico decide.

Criterios: condiciones de uso del Anexo del Reglamento (CE) 1924/2006 (modificado
por el Reglamento (UE) 1047/2012 para "sin sal añadida"). Valores por 100 g en
sólidos y por 100 ml en líquidos. Alcance del MVP: 14 declaraciones frecuentes;
las demás se marcan como "sin regla automática" y siguen el checklist manual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from app.preprocesamiento import normalizar_texto

CUMPLE = "CUMPLE"
NO_CUMPLE = "NO_CUMPLE"
REQUIERE_EVIDENCIA = "REQUIERE_EVIDENCIA"
DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"

ANEXO = "Reg. (CE) 1924/2006, Anexo"
EPS = 1e-9  # tolerancia de coma flotante en los límites (≤ y ≥ son inclusivos)

Resultado = tuple[str, Optional[float], str, str]  # veredicto, valor, unidad, detalle


@dataclass(frozen=True)
class Regla:
    id: str
    claim: str
    patron: re.Pattern
    criterio: str
    evaluar: Callable[[dict], Resultado]
    referencia: str = ANEXO


def _base(datos: dict) -> str:
    return "100 ml" if datos.get("estado_fisico") == "liquido" else "100 g"


def _maximo(campo: str, solido: float, liquido: float | None = None,
            factor: float = 1.0, unidad: str = "g") -> Callable[[dict], Resultado]:
    """Regla de contenido máximo (bajo en…, sin…)."""

    def evaluar(datos: dict) -> Resultado:
        valor = datos.get(campo)
        base = _base(datos)
        if valor is None:
            return DATOS_INSUFICIENTES, None, f"{unidad}/{base}", f"Falta el dato '{campo}' en la tabla nutrimental."
        es_liquido = datos.get("estado_fisico") == "liquido"
        limite = liquido if (es_liquido and liquido is not None) else solido
        valor = round(valor * factor, 6)
        cumple = valor <= limite + EPS
        signo = "≤" if cumple else ">"
        return (CUMPLE if cumple else NO_CUMPLE, valor, f"{unidad}/{base}",
                f"{valor:g} {unidad}/{base} {signo} {limite:g} {unidad}/{base}")

    return evaluar


def _fibra(min_100g: float, min_100kcal: float) -> Callable[[dict], Resultado]:
    """Fibra: basta con cumplir el criterio por 100 g o el criterio por 100 kcal."""

    def evaluar(datos: dict) -> Resultado:
        fibra = datos.get("fibra_g")
        energia = datos.get("energia_kcal")
        base = _base(datos)
        if fibra is None:
            return DATOS_INSUFICIENTES, None, f"g/{base}", "Falta el dato 'fibra_g' en la tabla nutrimental."
        if fibra >= min_100g - EPS:
            return CUMPLE, fibra, f"g/{base}", f"{fibra:g} g/{base} ≥ {min_100g:g} g/{base}"
        if energia is None or energia <= 0:
            return (DATOS_INSUFICIENTES, fibra, f"g/{base}",
                    f"{fibra:g} g/{base} < {min_100g:g} g; falta la energía para evaluar el criterio alterno "
                    f"de {min_100kcal:g} g/100 kcal.")
        por_kcal = round(fibra / energia * 100, 4)
        cumple = por_kcal >= min_100kcal - EPS
        signo = "≥" if cumple else "<"
        return (CUMPLE if cumple else NO_CUMPLE, por_kcal, "g/100 kcal",
                f"{fibra:g} g/{base} < {min_100g:g} g; criterio alterno: {por_kcal:g} g/100 kcal {signo} {min_100kcal:g}")

    return evaluar


def _proteina(min_pct: float) -> Callable[[dict], Resultado]:
    """Proteína: porcentaje del valor energético aportado por la proteína (4 kcal/g)."""

    def evaluar(datos: dict) -> Resultado:
        proteina = datos.get("proteina_g")
        energia = datos.get("energia_kcal")
        if proteina is None or energia is None or energia <= 0:
            return (DATOS_INSUFICIENTES, None, "% energía",
                    "Se necesitan 'proteina_g' y 'energia_kcal' (> 0) para calcular el % de energía.")
        pct = round(proteina * 4 / energia * 100, 2)
        cumple = pct >= min_pct - EPS
        signo = "≥" if cumple else "<"
        return CUMPLE if cumple else NO_CUMPLE, pct, "% energía", f"{pct:g} % de la energía {signo} {min_pct:g} %"

    return evaluar


def _sin_azucares_anadidos(datos: dict) -> Resultado:
    detalle = ("Verificar en la lista de ingredientes que no se añadieron monosacáridos, disacáridos "
               "ni otro alimento usado por sus propiedades edulcorantes.")
    azucares = datos.get("azucares_g")
    if azucares is not None and azucares > 0:
        detalle += (" El producto declara azúcares: si están naturalmente presentes, la etiqueta debe "
                    "indicar 'contiene azúcares naturalmente presentes'.")
    return REQUIERE_EVIDENCIA, azucares, f"g/{_base(datos)}", detalle


def _sin_sal_anadida(datos: dict) -> Resultado:
    sodio_mg = datos.get("sodio_mg")
    base = _base(datos)
    if sodio_mg is None:
        return DATOS_INSUFICIENTES, None, f"g de sodio/{base}", "Falta el dato 'sodio_mg' en la tabla nutrimental."
    sodio_g = round(sodio_mg / 1000, 6)
    if sodio_g > 0.12 + EPS:
        return NO_CUMPLE, sodio_g, f"g de sodio/{base}", f"{sodio_g:g} g de sodio/{base} > 0.12 g"
    return (REQUIERE_EVIDENCIA, sodio_g, f"g de sodio/{base}",
            f"{sodio_g:g} g de sodio/{base} ≤ 0.12 g; verificar además que ningún ingrediente aporte sal o sodio añadido.")


# ── Patrones (sobre texto normalizado: minúsculas y sin acentos) ────────────────
_DE = r"(?:en|de|contenido\s+(?:de|en))"
_SIN = r"(?:sin|libre\s+de|cero|0\s*%\s*(?:de\s+)?)"
_ANADIDO = r"(?:anadid[oa]s?|agregad[oa]s?)"


def _p(expresion: str) -> re.Pattern:
    return re.compile(expresion)


# El orden importa: la primera regla que coincide gana, así que las formas
# específicas ("muy bajo", "sin… añadidos") van antes que las generales.
REGLAS: list[Regla] = [
    Regla("R01", "Sin azúcares añadidos",
          _p(rf"\bsin\s+(?:adicion\s+de\s+)?azucar(?:es)?\s+{_ANADIDO}|\bsin\s+adicion\s+de\s+azucar"),
          "Sin azúcares añadidos (monosacáridos, disacáridos ni edulcorantes alimentarios)", _sin_azucares_anadidos),
    Regla("R02", "Sin azúcares", _p(rf"\b{_SIN}\s*azucar(?:es)?\b(?!\s+{_ANADIDO})"),
          "≤ 0.5 g de azúcares por 100 g o 100 ml", _maximo("azucares_g", 0.5, 0.5)),
    Regla("R03", "Bajo en azúcares", _p(rf"\bbaj[oa]\s+{_DE}\s+azucar"),
          "≤ 5 g por 100 g (sólidos) o ≤ 2.5 g por 100 ml (líquidos)", _maximo("azucares_g", 5, 2.5)),
    Regla("R04", "Sin grasa", _p(rf"\b{_SIN}\s*grasas?\b(?!\s+(?:saturad|trans))"),
          "≤ 0.5 g de grasa por 100 g o 100 ml", _maximo("grasa_g", 0.5, 0.5)),
    Regla("R05", "Bajo en grasa", _p(rf"\bbaj[oa]\s+{_DE}\s+grasas?\b(?!\s+(?:saturad|trans))"),
          "≤ 3 g por 100 g (sólidos) o ≤ 1.5 g por 100 ml (líquidos)", _maximo("grasa_g", 3, 1.5)),
    Regla("R06", "Sin sal añadida",
          _p(rf"\bsin\s+(?:sal|sodio)\s+{_ANADIDO}|\bsin\s+adicion\s+de\s+(?:sal|sodio)"),
          "Sin sal o sodio añadidos y ≤ 0.12 g de sodio por 100 g o 100 ml", _sin_sal_anadida,
          "Reg. (CE) 1924/2006, Anexo (modificado por Reg. (UE) 1047/2012)"),
    Regla("R07", "Sin sodio o sin sal", _p(rf"\b{_SIN}\s*(?:sal|sodio)\b(?!\s+{_ANADIDO})"),
          "≤ 0.005 g de sodio por 100 g o 100 ml", _maximo("sodio_mg", 0.005, 0.005, 0.001, "g de sodio")),
    Regla("R08", "Muy bajo en sodio o sal", _p(rf"\bmuy\s+baj[oa]\s+{_DE}\s+(?:sal|sodio)\b"),
          "≤ 0.04 g de sodio por 100 g o 100 ml", _maximo("sodio_mg", 0.04, 0.04, 0.001, "g de sodio")),
    Regla("R09", "Bajo en sodio o sal", _p(rf"\bbaj[oa]\s+{_DE}\s+(?:sal|sodio)\b"),
          "≤ 0.12 g de sodio por 100 g o 100 ml", _maximo("sodio_mg", 0.12, 0.12, 0.001, "g de sodio")),
    Regla("R10", "Alto contenido de fibra", _p(rf"\b(?:alt[oa]|ric[oa])\s+{_DE}\s+fibra"),
          "≥ 6 g por 100 g o ≥ 3 g por 100 kcal", _fibra(6, 3)),
    Regla("R11", "Fuente de fibra", _p(r"\bfuente\s+de\s+fibra"),
          "≥ 3 g por 100 g o ≥ 1.5 g por 100 kcal", _fibra(3, 1.5)),
    Regla("R12", "Alto contenido de proteínas", _p(rf"\b(?:alt[oa]|ric[oa])\s+{_DE}\s+proteinas?"),
          "La proteína aporta ≥ 20 % del valor energético", _proteina(20)),
    Regla("R13", "Fuente de proteínas", _p(r"\bfuente\s+de\s+proteinas?"),
          "La proteína aporta ≥ 12 % del valor energético", _proteina(12)),
    Regla("R14", "Bajo valor energético",
          _p(rf"\bbaj[oa]\s+(?:{_DE}\s+)?(?:calorias|energia)\b|\bbaj[oa]\s+valor\s+energetico"),
          "≤ 40 kcal por 100 g (sólidos) o ≤ 20 kcal por 100 ml (líquidos)", _maximo("energia_kcal", 40, 20, 1.0, "kcal")),
]


def buscar_regla(texto: str) -> Regla | None:
    """Devuelve la primera regla cuyo patrón aparece en el claim, o None."""
    normalizado = normalizar_texto(texto)
    for regla in REGLAS:
        if regla.patron.search(normalizado):
            return regla
    return None


def aplicar_regla(texto: str, datos: dict | None) -> dict | None:
    """Evalúa el claim contra su regla. Sin regla aplicable devuelve None."""
    regla = buscar_regla(texto)
    if regla is None:
        return None
    if datos is None and regla.id != "R01":
        veredicto, valor, unidad, detalle = (DATOS_INSUFICIENTES, None, "",
                                             "No se enviaron datos nutrimentales; la regla no puede evaluarse.")
    else:
        veredicto, valor, unidad, detalle = regla.evaluar(datos or {})
    return {
        "regla_id": regla.id,
        "claim_regulado": regla.claim,
        "criterio": regla.criterio,
        "veredicto_propuesto": veredicto,
        "valor_calculado": valor,
        "unidad": unidad,
        "detalle": detalle,
        "referencia": regla.referencia,
    }


def catalogo_reglas() -> list[dict]:
    return [{"regla_id": r.id, "claim_regulado": r.claim, "criterio": r.criterio, "referencia": r.referencia}
            for r in REGLAS]
