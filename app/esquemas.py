"""Contratos de la API (entrada y salida) con validación de Pydantic.

Toda entrada inválida se rechaza con HTTP 422 antes de llegar al modelo.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.config import LONGITUD_MAX_CLAIM, LONGITUD_MIN_CLAIM, MAX_CLAIMS_ETIQUETA, MAX_CLAIMS_LOTE

TextoClaim = Annotated[str, StringConstraints(strip_whitespace=True, min_length=LONGITUD_MIN_CLAIM,
                                              max_length=LONGITUD_MAX_CLAIM)]
Categoria = Literal["NUTRIMENTAL", "SALUD", "AUSENCIA", "MARKETING"]
Veredicto = Literal["CUMPLE", "NO_CUMPLE", "REQUIERE_EVIDENCIA", "DATOS_INSUFICIENTES"]


# ── Entradas ────────────────────────────────────────────────────────────────────
class ClaimEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"texto": "Fuente de fibra"}]})
    texto: TextoClaim = Field(description="Claim tal como aparece en el empaque (2 a 300 caracteres)")


class LoteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"claims": ["Sin gluten", "Receta tradicional", "El calcio ayuda a mantener los huesos"]}]})
    claims: list[TextoClaim] = Field(min_length=1, max_length=MAX_CLAIMS_LOTE)


class DatosNutrimentales(BaseModel):
    """Tabla nutrimental por 100 g (sólidos) o por 100 ml (líquidos)."""

    model_config = ConfigDict(extra="forbid")
    estado_fisico: Literal["solido", "liquido"] = "solido"
    energia_kcal: float | None = Field(None, ge=0, le=900)
    grasa_g: float | None = Field(None, ge=0, le=100)
    azucares_g: float | None = Field(None, ge=0, le=100)
    sodio_mg: float | None = Field(None, ge=0, le=40000)
    fibra_g: float | None = Field(None, ge=0, le=100)
    proteina_g: float | None = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _masa_posible(self):
        total = sum(v for v in (self.grasa_g, self.azucares_g, self.fibra_g, self.proteina_g) if v is not None)
        if total > 100.5:
            raise ValueError(
                f"Grasa + azúcares + fibra + proteína suman {total:g} g por 100 g/ml: "
                "los datos son físicamente imposibles.")
        return self


class EtiquetaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "producto": "Cereal integral de avena",
        "claims": ["Fuente de fibra", "Bajo en grasa", "Sin azúcares añadidos", "Sin gluten"],
        "datos_nutrimentales": {"estado_fisico": "solido", "energia_kcal": 372, "grasa_g": 6.5,
                                "azucares_g": 1.2, "sodio_mg": 8, "fibra_g": 9.8, "proteina_g": 13.1},
    }]})
    producto: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    claims: list[TextoClaim] = Field(min_length=1, max_length=MAX_CLAIMS_ETIQUETA)
    datos_nutrimentales: DatosNutrimentales | None = None


# ── Salidas ─────────────────────────────────────────────────────────────────────
class ResultadoRegla(BaseModel):
    regla_id: str
    claim_regulado: str
    criterio: str
    veredicto_propuesto: Veredicto
    valor_calculado: float | None
    unidad: str
    detalle: str
    referencia: str


class ResultadoClaim(BaseModel):
    texto: str
    categoria: Categoria
    confianza: float
    probabilidades: dict[str, float]
    checklist: str
    referencia_normativa: str
    requiere_confirmacion: bool = Field(description="True si el revisor debe confirmar el enrutamiento")
    motivos: list[str]
    regla: ResultadoRegla | None = None


class RespuestaLote(BaseModel):
    modelo_version: str
    umbral_confianza: float
    n_claims: int
    resultados: list[ResultadoClaim]


class ResumenEtiqueta(BaseModel):
    total_claims: int
    por_categoria: dict[str, int]
    por_veredicto: dict[str, int]
    claims_a_confirmar: int


class RespuestaEtiqueta(BaseModel):
    producto: str | None
    modelo_version: str
    umbral_confianza: float
    resumen: ResumenEtiqueta
    resultados: list[ResultadoClaim]
    aviso: str


class Salud(BaseModel):
    estado: Literal["ok"]
    version_api: str
    version_modelo: str
    modelo_cargado: bool
    integridad_verificada: bool
