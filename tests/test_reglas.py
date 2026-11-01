"""Pruebas unitarias del motor de reglas: detección del claim y límites exactos."""

import pytest

from app.reglas import (CUMPLE, DATOS_INSUFICIENTES, NO_CUMPLE, REGLAS, REQUIERE_EVIDENCIA, aplicar_regla,
                        buscar_regla)


@pytest.mark.parametrize("texto, regla_id", [
    ("Sin azúcares añadidos", "R01"),
    ("SIN AZUCAR AÑADIDA", "R01"),
    ("Sin adición de azúcares", "R01"),
    ("Sin azúcar", "R02"),
    ("Bajo en azúcares", "R03"),
    ("Sin grasa", "R04"),
    ("Bajo en grasa", "R05"),
    ("Bajo contenido de grasa", "R05"),
    ("Sin sal añadida", "R06"),
    ("Sin sodio", "R07"),
    ("Muy bajo en sal", "R08"),
    ("Bajo en sodio", "R09"),
    ("Alto contenido de fibra", "R10"),
    ("Rico en fibra", "R10"),
    ("Fuente de fibra", "R11"),
    ("Alto en proteína", "R12"),
    ("Fuente de proteínas", "R13"),
    ("Bajo en calorías", "R14"),
])
def test_detecta_la_regla_correcta(texto, regla_id):
    assert buscar_regla(texto).id == regla_id


@pytest.mark.parametrize("texto", [
    "Bajo en grasas saturadas",   # otra declaración (grasas saturadas), fuera del alcance del MVP
    "Sin gluten",                 # AUSENCIA, no es nutrimental
    "Salsa casera",               # 'sal' dentro de otra palabra
    "Receta tradicional",
])
def test_no_aplica_regla_fuera_de_alcance(texto):
    assert buscar_regla(texto) is None


def test_hay_14_reglas_con_identificador_unico():
    assert len(REGLAS) == 14 and len({r.id for r in REGLAS}) == 14


@pytest.mark.parametrize("estado, grasa, esperado", [
    ("solido", 3.0, CUMPLE),      # límite exacto: ≤ es inclusivo
    ("solido", 3.01, NO_CUMPLE),
    ("liquido", 1.5, CUMPLE),
    ("liquido", 1.6, NO_CUMPLE),  # el límite de líquidos es la mitad
])
def test_bajo_en_grasa_limites(estado, grasa, esperado):
    r = aplicar_regla("Bajo en grasa", {"estado_fisico": estado, "grasa_g": grasa})
    assert r["veredicto_propuesto"] == esperado


@pytest.mark.parametrize("sodio_mg, esperado", [(120, CUMPLE), (121, NO_CUMPLE)])
def test_bajo_en_sodio_convierte_mg_a_g(sodio_mg, esperado):
    r = aplicar_regla("Bajo en sodio", {"sodio_mg": sodio_mg})
    assert r["veredicto_propuesto"] == esperado and r["unidad"].startswith("g de sodio")


def test_fuente_de_fibra_por_100g():
    assert aplicar_regla("Fuente de fibra", {"fibra_g": 3})["veredicto_propuesto"] == CUMPLE


def test_fuente_de_fibra_criterio_alterno_por_100_kcal():
    # 2 g/100 g no alcanza 3 g, pero 2 g en 100 kcal = 2 g/100 kcal ≥ 1.5 → cumple
    r = aplicar_regla("Fuente de fibra", {"fibra_g": 2, "energia_kcal": 100})
    assert r["veredicto_propuesto"] == CUMPLE and r["unidad"] == "g/100 kcal"


def test_fuente_de_fibra_sin_energia_no_concluye():
    r = aplicar_regla("Fuente de fibra", {"fibra_g": 2})
    assert r["veredicto_propuesto"] == DATOS_INSUFICIENTES


@pytest.mark.parametrize("proteina, energia, esperado", [(12, 400, CUMPLE), (11.9, 400, NO_CUMPLE)])
def test_fuente_de_proteinas_porcentaje_energia(proteina, energia, esperado):
    # 12 g × 4 kcal/g / 400 kcal = 12 % exacto
    assert aplicar_regla("Fuente de proteínas",
                         {"proteina_g": proteina, "energia_kcal": energia})["veredicto_propuesto"] == esperado


def test_proteina_con_energia_cero_no_divide_entre_cero():
    r = aplicar_regla("Alto en proteínas", {"proteina_g": 10, "energia_kcal": 0})
    assert r["veredicto_propuesto"] == DATOS_INSUFICIENTES


def test_sin_azucares_anadidos_siempre_pide_evidencia():
    r = aplicar_regla("Sin azúcares añadidos", {"azucares_g": 6})
    assert r["veredicto_propuesto"] == REQUIERE_EVIDENCIA
    assert "naturalmente presentes" in r["detalle"]


def test_sin_sal_anadida_rechaza_por_sodio_alto():
    assert aplicar_regla("Sin sal añadida", {"sodio_mg": 300})["veredicto_propuesto"] == NO_CUMPLE
    assert aplicar_regla("Sin sal añadida", {"sodio_mg": 50})["veredicto_propuesto"] == REQUIERE_EVIDENCIA


def test_sin_datos_nutrimentales():
    assert aplicar_regla("Bajo en grasa", None)["veredicto_propuesto"] == DATOS_INSUFICIENTES
    assert aplicar_regla("Bajo en grasa", {})["veredicto_propuesto"] == DATOS_INSUFICIENTES


def test_bajo_valor_energetico_liquido():
    assert aplicar_regla("Bajo en calorías", {"estado_fisico": "liquido", "energia_kcal": 20})[
        "veredicto_propuesto"] == CUMPLE
    assert aplicar_regla("Bajo en calorías", {"estado_fisico": "liquido", "energia_kcal": 21})[
        "veredicto_propuesto"] == NO_CUMPLE
