"""Entrenamiento fuera de línea del enrutador de claims (ClaimCheck IA · Fase 2).

Uso (desde la raíz del repositorio):
    pip install -r requirements.txt
    python -m src.entrenar_modelo

Qué hace:
1. Lee data/claims_etiquetado.csv (dataset de la Actividad 4) y respeta su partición:
   `dev` (71 claims) para entrenar y elegir hiperparámetros; `test` (169) solo para medir.
   Es el mismo conjunto de prueba con el que se evaluaron los modelos zero-shot.
2. Elige C de la regresión logística con validación cruzada estratificada (5 pliegues) en `dev`.
3. Elige el umbral de confianza τ con las probabilidades fuera de pliegue de `dev`.
4. Entrena con todo `dev`, mide en `test` y guarda el artefacto, sus metadatos y las predicciones.

Solo depende de requirements.txt (scikit-learn, numpy, joblib): el modelo se puede
reconstruir con las mismas versiones que corren dentro del contenedor.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import FeatureUnion, Pipeline

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app.preprocesamiento import normalizar_texto  # noqa: E402

DATASET = RAIZ / "data" / "claims_etiquetado.csv"
DIR_MODELOS = RAIZ / "modelos"
DIR_RESULTADOS = RAIZ / "resultados"
NOMBRE = "claimcheck_router_v1"
VERSION = "1.0.0"
SEMILLA = 42
CLASES = ["AUSENCIA", "MARKETING", "NUTRIMENTAL", "SALUD"]
REJILLA_C = [1, 5, 10, 20]
REJILLA_TAU = [round(x, 2) for x in np.arange(0.30, 0.91, 0.05)]
EXACTITUD_AUTO_MIN = 0.90  # criterio de la Actividad 4 para lo que se enruta sin confirmación
UMBRALES_NEGOCIO = {"f1_macro_min": 0.80, "recall_salud_min": 0.90}  # mismos que la Actividad 4

# Mejores resultados zero-shot de la Actividad 4 (mismo conjunto test, 169 claims) — results/resumen.json
REFERENCIA_ACTIVIDAD4 = {
    "MiniLM-L6": {"f1_macro": 0.5372, "accuracy": 0.5503, "recall_salud": 0.8095, "ms_claim_cpu": 377.1},
    "mDeBERTa-base": {"f1_macro": 0.5994, "accuracy": 0.6095, "recall_salud": 0.8571, "ms_claim_cpu": 10642.0},
    "XLM-R-large": {"f1_macro": 0.5916, "accuracy": 0.6154, "recall_salud": 0.2857, "ms_claim_cpu": 1810.2},
}


def construir_pipeline(c: float) -> Pipeline:
    caracteristicas = FeatureUnion([
        ("palabras", TfidfVectorizer(preprocessor=normalizar_texto, ngram_range=(1, 2), sublinear_tf=True)),
        ("caracteres", TfidfVectorizer(preprocessor=normalizar_texto, analyzer="char_wb", ngram_range=(2, 5),
                                       sublinear_tf=True)),
    ])
    clasificador = LogisticRegression(C=c, class_weight="balanced", max_iter=5000, random_state=SEMILLA)
    return Pipeline([("tfidf", caracteristicas), ("clasificador", clasificador)])


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def leer_dataset() -> list[dict]:
    with open(DATASET, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def elegir_tau(y_real: np.ndarray, probas: np.ndarray, clases: list[str]) -> tuple[float, list[dict]]:
    pred = np.array(clases)[probas.argmax(1)]
    conf = probas.max(1)
    curva = []
    for tau in REJILLA_TAU:
        auto = conf >= tau
        cobertura = float(auto.mean())
        exactitud = float((pred[auto] == y_real[auto]).mean()) if auto.any() else None
        curva.append({"tau": tau, "cobertura": round(cobertura, 4),
                      "exactitud_auto": None if exactitud is None else round(exactitud, 4)})
    validos = [p for p in curva if p["exactitud_auto"] is not None and p["exactitud_auto"] >= EXACTITUD_AUTO_MIN]
    tau = min(p["tau"] for p in validos) if validos else REJILLA_TAU[-1]
    return tau, curva


def main() -> None:
    filas = leer_dataset()
    dev = [f for f in filas if f["particion"] == "dev"]
    test = [f for f in filas if f["particion"] == "test"]
    x_dev, y_dev = [f["texto_claim"] for f in dev], np.array([f["categoria"] for f in dev])
    x_test, y_test = [f["texto_claim"] for f in test], np.array([f["categoria"] for f in test])
    print(f"Dataset: {len(filas)} claims · entrenamiento (dev) {len(dev)} · prueba (test) {len(test)}")

    # 1) Hiperparámetro C por validación cruzada en dev (el test no se toca)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEMILLA)
    resultados_cv = {}
    for c in REJILLA_C:
        puntajes = cross_val_score(construir_pipeline(c), x_dev, y_dev, cv=cv, scoring="f1_macro")
        resultados_cv[c] = {"f1_macro_media": round(float(puntajes.mean()), 4),
                            "f1_macro_desv": round(float(puntajes.std()), 4)}
        print(f"  C={c:<3} macro-F1 CV = {puntajes.mean():.3f} ± {puntajes.std():.3f}")
    mejor_c = max(REJILLA_C, key=lambda c: (resultados_cv[c]["f1_macro_media"], -c))
    print(f"C elegido: {mejor_c}")

    # 2) Umbral τ con probabilidades fuera de pliegue en dev
    probas_oof = cross_val_predict(construir_pipeline(mejor_c), x_dev, y_dev, cv=cv, method="predict_proba")
    tau, curva_dev = elegir_tau(y_dev, probas_oof, CLASES)
    print(f"τ elegido en dev: {tau:.2f}")

    # 3) Modelo final y evaluación en test
    modelo = construir_pipeline(mejor_c).fit(x_dev, y_dev)
    assert list(modelo.classes_) == CLASES
    probas = modelo.predict_proba(x_test)
    pred = np.array(CLASES)[probas.argmax(1)]
    conf = probas.max(1)
    p, r, f, s = precision_recall_fscore_support(y_test, pred, labels=CLASES, zero_division=0)
    ambiguos = np.array([t["dificultad"] == "ambiguo" for t in test])
    auto = conf >= tau
    globales = {
        "accuracy": round(accuracy_score(y_test, pred), 4),
        "precision_macro": round(float(p.mean()), 4),
        "recall_macro": round(float(r.mean()), 4),
        "f1_macro": round(f1_score(y_test, pred, average="macro"), 4),
        "f1_ponderado": round(f1_score(y_test, pred, average="weighted"), 4),
        "recall_salud": round(float(r[CLASES.index("SALUD")]), 4),
        "accuracy_casos_frontera": round(float((pred[ambiguos] == y_test[ambiguos]).mean()), 4),
        "n_casos_frontera": int(ambiguos.sum()),
        "accuracy_estandar": round(float((pred[~ambiguos] == y_test[~ambiguos]).mean()), 4),
        "cobertura_auto": round(float(auto.mean()), 4),
        "exactitud_auto": round(float((pred[auto] == y_test[auto]).mean()), 4) if auto.any() else None,
        "exactitud_a_confirmar": round(float((pred[~auto] == y_test[~auto]).mean()), 4) if (~auto).any() else None,
    }
    por_clase = {c: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                     "f1": round(float(f[i]), 4), "soporte": int(s[i])} for i, c in enumerate(CLASES)}
    _, curva_test = elegir_tau(y_test, probas, CLASES)
    print(f"Test: accuracy {globales['accuracy']:.3f} · macro-F1 {globales['f1_macro']:.3f} · "
          f"recall SALUD {globales['recall_salud']:.3f} · cobertura τ {globales['cobertura_auto']:.0%} "
          f"con exactitud {globales['exactitud_auto']}")

    # 4) Persistencia: artefacto + metadatos (trazabilidad ISO/IEC 23053)
    DIR_MODELOS.mkdir(exist_ok=True)
    DIR_RESULTADOS.mkdir(exist_ok=True)
    ruta_modelo = DIR_MODELOS / f"{NOMBRE}.joblib"
    joblib.dump(modelo, ruta_modelo, compress=3)

    metadatos = {
        "nombre": NOMBRE,
        "version": VERSION,
        "proyecto": "ClaimCheck IA · Fase 2 (CertiBajío, S.C., organismo certificador ficticio)",
        "proposito": "Enrutar cada claim de etiquetado a su checklist de revisión; el revisor técnico decide.",
        "fecha_entrenamiento": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "algoritmo": "TF-IDF (palabras 1-2 + caracteres 2-5, normalización sin acentos) + regresión logística "
                     "multinomial con pesos balanceados",
        "hiperparametros": {"C": mejor_c, "class_weight": "balanced", "max_iter": 5000,
                            "ngramas_palabras": [1, 2], "ngramas_caracteres": [2, 5], "sublinear_tf": True},
        "clases": CLASES,
        "datos": {"archivo": "data/claims_etiquetado.csv", "sha256": sha256(DATASET), "total": len(filas),
                  "entrenamiento": {"particion": "dev", "n": len(dev)},
                  "prueba": {"particion": "test", "n": len(test)}},
        "seleccion": {"validacion_cruzada": "StratifiedKFold(5, shuffle, semilla 42) sobre dev",
                      "rejilla_C": resultados_cv, "C_elegido": mejor_c},
        "umbral_confianza": {"valor": tau, "criterio": f"menor τ con exactitud ≥ {EXACTITUD_AUTO_MIN:.0%} en lo "
                             "que se enruta sin confirmación (probabilidades fuera de pliegue en dev)",
                             "curva_dev": curva_dev},
        "metricas_prueba": {"globales": globales, "por_clase": por_clase,
                            "matriz_confusion": {"clases": CLASES,
                                                 "valores": confusion_matrix(y_test, pred, labels=CLASES).tolist()},
                            "curva_tau": curva_test},
        "umbrales_negocio": UMBRALES_NEGOCIO,
        "cumple_umbrales": {"f1_macro": globales["f1_macro"] >= UMBRALES_NEGOCIO["f1_macro_min"],
                            "recall_salud": globales["recall_salud"] >= UMBRALES_NEGOCIO["recall_salud_min"]},
        "referencia_actividad4_zero_shot": REFERENCIA_ACTIVIDAD4,
        "entorno": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                    "numpy": np.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__,
                    "plataforma": platform.platform(), "semilla": SEMILLA},
        "artefacto": {"archivo": f"modelos/{ruta_modelo.name}", "sha256": sha256(ruta_modelo),
                      "bytes": ruta_modelo.stat().st_size, "formato": "joblib (pickle comprimido)"},
        "limitaciones": [
            "Dataset propio de 240 claims en español; más limpio que etiquetas reales (sin OCR ni claims combinados).",
            "Entrenado con 71 claims: es una línea base desplegable, no el modelo final de producción.",
            "Una sola categoría por claim; el motor de reglas evalúa una regla por claim.",
        ],
    }
    (DIR_MODELOS / f"{NOMBRE}.json").write_text(json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(DIR_RESULTADOS / "predicciones_test.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id_claim", "texto_claim", "categoria_real", "categoria_predicha", "confianza", "acierto",
                    "requiere_confirmacion", "dificultad", "subtipo"])
        for t, pr, cf in zip(test, pred, conf):
            w.writerow([t["id_claim"], t["texto_claim"], t["categoria"], pr, f"{cf:.4f}",
                        int(pr == t["categoria"]), int(cf < tau), t["dificultad"], t["subtipo"]])
    (DIR_RESULTADOS / "metricas_modelo.json").write_text(json.dumps({
        "modelo": NOMBRE, "version": VERSION, "C": mejor_c, "tau": tau, "metricas_prueba": metadatos["metricas_prueba"],
        "cumple_umbrales": metadatos["cumple_umbrales"], "referencia_actividad4_zero_shot": REFERENCIA_ACTIVIDAD4,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Artefacto: {ruta_modelo.relative_to(RAIZ)} ({ruta_modelo.stat().st_size / 1024:.0f} KB) · "
          f"SHA-256 {metadatos['artefacto']['sha256'][:16]}…")


if __name__ == "__main__":
    main()
