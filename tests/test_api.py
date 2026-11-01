"""Pruebas de la API (integración backend) con casos funcionales y extremos."""

import pytest

ETIQUETA = {
    "producto": "Cereal integral de avena",
    "claims": ["Fuente de fibra", "Bajo en grasa", "Sin azúcares añadidos", "Sin gluten"],
    "datos_nutrimentales": {"estado_fisico": "solido", "energia_kcal": 372, "grasa_g": 6.5,
                            "azucares_g": 1.2, "sodio_mg": 8, "fibra_g": 9.8, "proteina_g": 13.1},
}


# ── Operación ───────────────────────────────────────────────────────────────────
def test_health(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "ok" and cuerpo["modelo_cargado"] and cuerpo["integridad_verificada"]


def test_info_y_reglas(cliente):
    info = cliente.get("/api/v1/info").json()
    assert info["clases"] == ["AUSENCIA", "MARKETING", "NUTRIMENTAL", "SALUD"]
    assert 0 < info["umbral_confianza"] < 1
    assert cliente.get("/api/v1/reglas").json()["total"] == 14


def test_openapi_documenta_los_endpoints(cliente):
    rutas = cliente.get("/openapi.json").json()["paths"]
    for ruta in ["/health", "/api/v1/clasificar", "/api/v1/clasificar/lote", "/api/v1/analizar-etiqueta"]:
        assert ruta in rutas


def test_frontend_se_sirve(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "ClaimCheck" in r.text
    assert cliente.get("/static/app.js").status_code == 200


def test_cabeceras_de_trazabilidad(cliente):
    r = cliente.post("/api/v1/clasificar", json={"texto": "Sin gluten"}, headers={"X-Request-ID": "prueba-123"})
    assert r.headers["X-Request-ID"] == "prueba-123"
    assert float(r.headers["X-Tiempo-Proceso-ms"]) >= 0


# ── Funcionales ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("texto, categoria", [
    ("Sin gluten", "AUSENCIA"),
    ("Receta tradicional", "MARKETING"),
    ("Bajo en sodio", "NUTRIMENTAL"),
    ("El calcio es necesario para el mantenimiento de los huesos en condiciones normales", "SALUD"),
])
def test_clasificar(cliente, texto, categoria):
    r = cliente.post("/api/v1/clasificar", json={"texto": texto})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["categoria"] == categoria
    assert cuerpo["checklist"].startswith("CL-")


def test_lote_conserva_el_orden(cliente):
    claims = ["Sin gluten", "Receta tradicional", "Bajo en sodio"]
    r = cliente.post("/api/v1/clasificar/lote", json={"claims": claims})
    assert r.status_code == 200
    assert [x["texto"] for x in r.json()["resultados"]] == claims


def test_analizar_etiqueta_aplica_reglas(cliente):
    r = cliente.post("/api/v1/analizar-etiqueta", json=ETIQUETA)
    assert r.status_code == 200
    por_texto = {x["texto"]: x for x in r.json()["resultados"]}
    assert por_texto["Fuente de fibra"]["regla"]["veredicto_propuesto"] == "CUMPLE"       # 9.8 g ≥ 3 g
    assert por_texto["Bajo en grasa"]["regla"]["veredicto_propuesto"] == "NO_CUMPLE"      # 6.5 g > 3 g
    assert por_texto["Sin azúcares añadidos"]["regla"]["veredicto_propuesto"] == "REQUIERE_EVIDENCIA"
    assert por_texto["Sin gluten"]["regla"] is None
    assert "revisor decide" in r.json()["aviso"]


def test_texto_se_limpia_de_espacios(cliente):
    assert cliente.post("/api/v1/clasificar", json={"texto": "   Sin gluten   "}).json()["texto"] == "Sin gluten"


# ── Casos extremos: entradas inválidas → 4xx, nunca 500 ─────────────────────────
@pytest.mark.parametrize("cuerpo", [
    {"texto": ""},
    {"texto": "     "},
    {"texto": "a"},
    {"texto": "x" * 301},
    {"texto": 123},
    {"texto": None},
    {},
    {"texto": "Sin gluten", "campo_extra": 1},
])
def test_clasificar_rechaza_entradas_invalidas(cliente, cuerpo):
    assert cliente.post("/api/v1/clasificar", json=cuerpo).status_code == 422


def test_longitud_maxima_exacta_se_acepta(cliente):
    assert cliente.post("/api/v1/clasificar", json={"texto": "x" * 300}).status_code == 200


def test_json_malformado(cliente):
    r = cliente.post("/api/v1/clasificar", content=b'{"texto": "Sin gluten"',
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize("claims", [[], ["Sin gluten"] * 51])
def test_lote_fuera_de_limites(cliente, claims):
    assert cliente.post("/api/v1/clasificar/lote", json={"claims": claims}).status_code == 422


def test_lote_de_50_se_acepta(cliente):
    assert cliente.post("/api/v1/clasificar/lote", json={"claims": ["Sin gluten"] * 50}).status_code == 200


def test_cuerpo_demasiado_grande(cliente):
    r = cliente.post("/api/v1/clasificar", content=b"x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("datos", [
    {"grasa_g": -1},
    {"sodio_mg": 50_000},
    {"estado_fisico": "gaseoso"},
    {"grasa_g": 80, "proteina_g": 40},  # 120 g por 100 g: imposible
])
def test_datos_nutrimentales_invalidos(cliente, datos):
    cuerpo = {"claims": ["Bajo en grasa"], "datos_nutrimentales": datos}
    assert cliente.post("/api/v1/analizar-etiqueta", json=cuerpo).status_code == 422


@pytest.mark.parametrize("texto", [
    "🍎🍎🍎", "123456", "<script>alert(1)</script>", "'; DROP TABLE claims;--", "Gluten free", "ñññ ççç",
])
def test_textos_atipicos_no_rompen_el_servicio(cliente, texto):
    r = cliente.post("/api/v1/clasificar", json={"texto": texto})
    assert r.status_code == 200
    assert r.json()["texto"] == texto  # se devuelve como dato; el frontend lo muestra como texto, no como HTML


def test_inconsistencia_modelo_regla_pide_confirmacion(cliente):
    """Si la regla reconoce un claim nutrimental y el modelo propone otra clase, se marca para el revisor."""
    r = cliente.post("/api/v1/clasificar/lote", json={"claims": ["Sin sal añadida", "Sin azúcares añadidos"]})
    for x in r.json()["resultados"]:
        if x["categoria"] != "NUTRIMENTAL":
            assert x["requiere_confirmacion"] and any("regla" in m for m in x["motivos"])


def test_ruta_inexistente_y_metodo_no_permitido(cliente):
    assert cliente.get("/api/v1/no-existe").status_code == 404
    assert cliente.get("/api/v1/clasificar").status_code == 405
