"""Pruebas del artefacto del modelo: integridad, contrato de salida y desempeño mínimo."""

import csv
import json
import shutil

import pytest
from sklearn.metrics import f1_score

from app.config import RAIZ, Config
from app.modelo import ErrorIntegridad, ServicioModelo
from app.preprocesamiento import normalizar_texto

CONFIG = Config()


@pytest.fixture(scope="module")
def servicio():
    s = ServicioModelo(CONFIG.ruta_modelo, CONFIG.ruta_metadatos)
    s.cargar()
    return s


def leer_test():
    with open(RAIZ / "data" / "claims_etiquetado.csv", encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["particion"] == "test"]


def test_normalizacion():
    assert normalizar_texto("  Sin AZÚCARES   añadidos ") == "sin azucares anadidos"


def test_integridad_verificada(servicio):
    assert servicio.integridad_verificada
    assert servicio.clases == ["AUSENCIA", "MARKETING", "NUTRIMENTAL", "SALUD"]


def test_artefacto_alterado_no_se_carga(tmp_path):
    copia = tmp_path / "modelo.joblib"
    shutil.copy(CONFIG.ruta_modelo, copia)
    with open(copia, "ab") as f:
        f.write(b"alterado")
    with pytest.raises(ErrorIntegridad):
        ServicioModelo(copia, CONFIG.ruta_metadatos).cargar()


def test_probabilidades_validas(servicio):
    for r in servicio.predecir(["Sin gluten", "Receta tradicional", "Fuente de fibra"]):
        assert abs(sum(r["probabilidades"].values()) - 1) < 1e-3
        assert r["confianza"] == max(r["probabilidades"].values())


def test_prediccion_determinista(servicio):
    assert servicio.predecir(["Bajo en sodio"] * 3) == servicio.predecir(["Bajo en sodio"]) * 3


def test_acentos_y_mayusculas_no_cambian_la_prediccion(servicio):
    a, b = servicio.predecir(["Sin azúcares añadidos", "SIN AZUCARES ANADIDOS"])
    assert a == b


def test_desempeno_en_test_no_retrocede(servicio):
    """Regresión: el macro-F1 en el conjunto de prueba coincide con el registrado en los metadatos."""
    filas = leer_test()
    pred = [r["categoria"] for r in servicio.predecir([f["texto_claim"] for f in filas])]
    f1 = f1_score([f["categoria"] for f in filas], pred, average="macro")
    registrado = json.loads(CONFIG.ruta_metadatos.read_text(encoding="utf-8"))["metricas_prueba"]["globales"]
    assert f1 == pytest.approx(registrado["f1_macro"], abs=1e-3)
    assert f1 >= 0.80  # umbral de negocio de la Actividad 4
