"""Validación de punta a punta contra el contenedor (o el servicio en la nube) en ejecución.

Solo usa la biblioteca estándar de Python: corre en cualquier equipo con Python 3.9+,
sin instalar nada, mientras el contenedor esté levantado.

    python scripts/validar_contenedor.py                                  # http://localhost:8000
    python scripts/validar_contenedor.py --url https://claimcheck-api.onrender.com --etiqueta render

Grupos de pruebas:
    D  Disponibilidad      (health, metadatos, frontend, OpenAPI)
    F  Funcionales         (clasificación por clase, lote, análisis de etiqueta con reglas)
    R  Reproducibilidad    (las 169 predicciones del test vía API = predicciones fuera de línea)
    E  Casos extremos      (entradas inválidas, límites, textos atípicos, rutas y métodos)
    P  Rendimiento         (latencia secuencial, concurrencia y lote)

Escribe un JSON con cada prueba (esperado, obtenido, estado) y termina con código 1 si alguna falla.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CLASES = ["AUSENCIA", "MARKETING", "NUTRIMENTAL", "SALUD"]


class Cliente:
    def __init__(self, url: str, timeout: float = 30):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def solicitar(self, metodo: str, ruta: str, cuerpo=None, crudo: bytes | None = None,
                  cabeceras: dict | None = None):
        datos = crudo if crudo is not None else (json.dumps(cuerpo).encode() if cuerpo is not None else None)
        h = {"Content-Type": "application/json"}
        h.update(cabeceras or {})
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo, headers=h)
        inicio = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                estado, texto, resp_h = r.status, r.read().decode("utf-8"), dict(r.headers)
        except urllib.error.HTTPError as e:
            estado, texto, resp_h = e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
        ms = (time.perf_counter() - inicio) * 1000
        try:
            contenido = json.loads(texto)
        except ValueError:
            contenido = texto
        return estado, contenido, resp_h, ms


class Registro:
    def __init__(self):
        self.pruebas: list[dict] = []

    def agregar(self, id_: str, grupo: str, descripcion: str, esperado: str, obtenido: str, ok: bool):
        self.pruebas.append({"id": id_, "grupo": grupo, "descripcion": descripcion, "esperado": esperado,
                             "obtenido": obtenido, "estado": "APROBADA" if ok else "FALLIDA"})
        marca = "✔" if ok else "✘"
        print(f"  {marca} {id_:<5} {descripcion[:62]:<62} → {obtenido[:60]}")


def percentil(valores: list[float], p: float) -> float:
    v = sorted(valores)
    k = (len(v) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


# ── D · Disponibilidad ──────────────────────────────────────────────────────────
def disponibilidad(c: Cliente, reg: Registro) -> dict:
    print("\nD · Disponibilidad")
    s, salud, _, ms = c.solicitar("GET", "/health")
    ok = s == 200 and isinstance(salud, dict) and salud.get("estado") == "ok" and salud.get("integridad_verificada")
    reg.agregar("D-01", "Disponibilidad", "GET /health: servicio vivo y modelo íntegro",
                "200, estado ok, SHA-256 verificado", f"{s}, {salud if s != 200 else 'ok, integridad ' + str(salud.get('integridad_verificada'))}", ok)
    s, info, _, _ = c.solicitar("GET", "/api/v1/info")
    ok = s == 200 and info.get("clases") == CLASES
    reg.agregar("D-02", "Disponibilidad", "GET /api/v1/info: metadatos del modelo", "200 y 4 clases",
                f"{s}, v{info.get('version_modelo')}, τ={info.get('umbral_confianza')}", ok)
    s, html, _, _ = c.solicitar("GET", "/")
    reg.agregar("D-03", "Disponibilidad", "GET /: el backend sirve el frontend", "200 y HTML de ClaimCheck",
                f"{s}, HTML {'con' if 'ClaimCheck' in str(html) else 'sin'} título", s == 200 and "ClaimCheck" in str(html))
    s, _, _, _ = c.solicitar("GET", "/static/app.js")
    reg.agregar("D-04", "Disponibilidad", "GET /static/app.js: cliente JavaScript", "200", str(s), s == 200)
    s, esquema, _, _ = c.solicitar("GET", "/openapi.json")
    rutas = list(esquema.get("paths", {})) if isinstance(esquema, dict) else []
    esperadas = ["/health", "/api/v1/info", "/api/v1/reglas", "/api/v1/clasificar", "/api/v1/clasificar/lote",
                 "/api/v1/analizar-etiqueta"]
    reg.agregar("D-05", "Disponibilidad", "GET /openapi.json: contrato de la API publicado",
                "6 endpoints documentados", f"{s}, {sum(r in rutas for r in esperadas)}/6 endpoints",
                s == 200 and all(r in rutas for r in esperadas))
    s, _, _, _ = c.solicitar("GET", "/docs")
    reg.agregar("D-06", "Disponibilidad", "GET /docs: documentación interactiva (Swagger UI)", "200", str(s), s == 200)
    return info if isinstance(info, dict) else {}


# ── F · Funcionales ─────────────────────────────────────────────────────────────
def funcionales(c: Cliente, reg: Registro) -> None:
    print("\nF · Funcionales")
    casos = [("F-01", "Sin gluten", "AUSENCIA"), ("F-02", "Receta tradicional", "MARKETING"),
             ("F-03", "Bajo en sodio", "NUTRIMENTAL"),
             ("F-04", "El calcio es necesario para el mantenimiento de los huesos en condiciones normales", "SALUD")]
    for id_, texto, esperado in casos:
        s, r, _, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": texto})
        obt = f"{s}, {r.get('categoria')} ({r.get('confianza')})" if s == 200 else f"{s}"
        reg.agregar(id_, "Funcional", f"Clasificar «{texto[:38]}»", f"200, {esperado}", obt,
                    s == 200 and r.get("categoria") == esperado and r.get("checklist", "").startswith("CL-"))

    claims = ["Sin gluten", "Receta tradicional", "Bajo en sodio"]
    s, r, _, _ = c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": claims})
    orden = [x["texto"] for x in r.get("resultados", [])] if s == 200 else []
    reg.agregar("F-05", "Funcional", "Lote de 3 claims conserva el orden", "200 y mismo orden",
                f"{s}, n={r.get('n_claims') if s == 200 else '-'}", s == 200 and orden == claims)

    etiqueta = {"producto": "Cereal integral de avena",
                "claims": ["Fuente de fibra", "Bajo en grasa", "Sin azúcares añadidos", "Sin gluten"],
                "datos_nutrimentales": {"estado_fisico": "solido", "energia_kcal": 372, "grasa_g": 6.5,
                                        "azucares_g": 1.2, "sodio_mg": 8, "fibra_g": 9.8, "proteina_g": 13.1}}
    s, r, _, _ = c.solicitar("POST", "/api/v1/analizar-etiqueta", etiqueta)
    v = {x["texto"]: (x["regla"] or {}).get("veredicto_propuesto") for x in r.get("resultados", [])} if s == 200 else {}
    esperado = {"Fuente de fibra": "CUMPLE", "Bajo en grasa": "NO_CUMPLE",
                "Sin azúcares añadidos": "REQUIERE_EVIDENCIA", "Sin gluten": None}
    reg.agregar("F-06", "Funcional", "Etiqueta sólida (cereal): reglas de fibra, grasa y azúcares",
                "fibra CUMPLE · grasa NO_CUMPLE · azúcares REQUIERE_EVIDENCIA · gluten sin regla",
                f"{s}, " + " · ".join(f"{corto} {v.get(k)}" for corto, k in zip(["fibra", "grasa", "azúcares", "gluten"],
                                                                              esperado)), s == 200 and v == esperado)

    bebida = {"producto": "Bebida de avena", "claims": ["Bajo en azúcares", "Bajo valor energético", "Fuente de proteínas"],
              "datos_nutrimentales": {"estado_fisico": "liquido", "energia_kcal": 18, "azucares_g": 2.0,
                                      "proteina_g": 0.5}}
    s, r, _, _ = c.solicitar("POST", "/api/v1/analizar-etiqueta", bebida)
    v = [(x["regla"] or {}).get("veredicto_propuesto") for x in r.get("resultados", [])] if s == 200 else []
    reg.agregar("F-07", "Funcional", "Etiqueta líquida: umbrales por 100 ml y % de energía",
                "CUMPLE · CUMPLE · NO_CUMPLE (11.1 % < 12 %)", f"{s}, {' · '.join(map(str, v))}",
                s == 200 and v == ["CUMPLE", "CUMPLE", "NO_CUMPLE"])

    s, _, h, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": "Sin gluten"}, cabeceras={"X-Request-ID": "val-001"})
    reg.agregar("F-08", "Funcional", "Trazabilidad: la API devuelve X-Request-ID y tiempo de proceso",
                "X-Request-ID = val-001", f"{s}, {h.get('X-Request-ID') or h.get('x-request-id')}",
                s == 200 and (h.get("X-Request-ID") or h.get("x-request-id")) == "val-001")


# ── R · Reproducibilidad ────────────────────────────────────────────────────────
def reproducibilidad(c: Cliente, reg: Registro, info: dict) -> dict:
    print("\nR · Reproducibilidad (modelo dentro del contenedor vs. entrenamiento fuera de línea)")
    with open(RAIZ / "resultados" / "predicciones_test.csv", encoding="utf-8", newline="") as f:
        offline = list(csv.DictReader(f))
    api = []
    for i in range(0, len(offline), 50):
        bloque = [o["texto_claim"] for o in offline[i:i + 50]]
        s, r, _, _ = c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": bloque})
        if s != 200:
            reg.agregar("R-01", "Reproducibilidad", "Predicciones del test vía API", "200", str(s), False)
            return {}
        api.extend(r["resultados"])
    iguales = sum(a["categoria"] == o["categoria_predicha"] for a, o in zip(api, offline))
    dif_conf = max(abs(a["confianza"] - float(o["confianza"])) for a, o in zip(api, offline))
    reg.agregar("R-01", "Reproducibilidad", f"Las {len(offline)} predicciones del test vía API = fuera de línea",
                f"{len(offline)}/{len(offline)} iguales", f"{iguales}/{len(offline)} iguales, Δconfianza máx {dif_conf:.1e}",
                iguales == len(offline) and dif_conf < 1e-3)

    reales = [o["categoria_real"] for o in offline]
    pred = [a["categoria"] for a in api]
    f1s = []
    for clase in CLASES:
        tp = sum(p == clase and y == clase for p, y in zip(pred, reales))
        fp = sum(p == clase and y != clase for p, y in zip(pred, reales))
        fn = sum(p != clase and y == clase for p, y in zip(pred, reales))
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
    f1_api = sum(f1s) / len(f1s)
    f1_reg = (info.get("metricas_prueba") or {}).get("f1_macro")
    reg.agregar("R-02", "Reproducibilidad", "Macro-F1 recalculado con las respuestas de la API",
                f"= {f1_reg} (metadatos)", f"{f1_api:.4f}", f1_reg is not None and abs(f1_api - f1_reg) < 1e-3)

    errores = [(a, y) for a, y in zip(api, reales) if a["categoria"] != y]
    marcados = sum(a["requiere_confirmacion"] for a, _ in errores)
    marcados_total = sum(a["requiere_confirmacion"] for a in api)
    por_tau = sum(any("umbral" in m for m in a["motivos"]) for a, _ in errores)
    por_regla = sum(any("regla" in m for m in a["motivos"]) for a, _ in errores)
    aciertos_auto = sum(a["categoria"] == y for a, y in zip(api, reales) if not a["requiere_confirmacion"])
    n_auto = sum(not a["requiere_confirmacion"] for a in api)
    reg.agregar("R-03", "Reproducibilidad", "Errores del modelo que el sistema marca para el revisor",
                "Métrica (se reporta)", f"{marcados}/{len(errores)} errores marcados (τ {por_tau}, regla {por_regla})", True)
    return {"n": len(offline), "iguales": iguales, "f1_macro_api": round(f1_api, 4), "errores": len(errores),
            "errores_marcados": marcados, "errores_marcados_por_tau": por_tau, "errores_marcados_por_regla": por_regla,
            "claims_marcados": marcados_total, "exactitud_sin_confirmacion": round(aciertos_auto / n_auto, 4) if n_auto else None,
            "cobertura_sin_confirmacion": round(n_auto / len(api), 4),
            "errores_detalle": [{"texto": a["texto"], "real": y, "predicha": a["categoria"], "confianza": a["confianza"],
                                 "marcado": a["requiere_confirmacion"], "motivos": a["motivos"]} for a, y in errores]}


# ── E · Casos extremos ──────────────────────────────────────────────────────────
def extremos(c: Cliente, reg: Registro) -> None:
    print("\nE · Casos extremos")
    invalidos = [
        ("E-01", "Texto vacío", {"texto": ""}),
        ("E-02", "Solo espacios", {"texto": "      "}),
        ("E-03", "Un carácter (mínimo 2)", {"texto": "a"}),
        ("E-04", "301 caracteres (máximo 300)", {"texto": "x" * 301}),
        ("E-05", "Tipo incorrecto (número)", {"texto": 12345}),
        ("E-06", "Campo obligatorio ausente", {}),
        ("E-07", "Campo no permitido", {"texto": "Sin gluten", "admin": True}),
    ]
    for id_, desc, cuerpo in invalidos:
        s, r, _, _ = c.solicitar("POST", "/api/v1/clasificar", cuerpo)
        reg.agregar(id_, "Casos extremos", desc, "422 (validación)", str(s), s == 422)

    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": "x" * 300})
    reg.agregar("E-08", "Casos extremos", "Exactamente 300 caracteres (límite)", "200", str(s), s == 200)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar", crudo=b'{"texto": "Sin gluten"')
    reg.agregar("E-09", "Casos extremos", "JSON malformado", "422", str(s), s == 422)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar", crudo=b"Sin gluten", cabeceras={"Content-Type": "text/plain"})
    reg.agregar("E-10", "Casos extremos", "Content-Type text/plain en lugar de JSON", "422", str(s), s == 422)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": []})
    reg.agregar("E-11", "Casos extremos", "Lote vacío", "422", str(s), s == 422)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": ["Sin gluten"] * 51})
    reg.agregar("E-12", "Casos extremos", "Lote de 51 claims (máximo 50)", "422", str(s), s == 422)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": ["Sin gluten"] * 50})
    reg.agregar("E-13", "Casos extremos", "Lote de 50 claims (límite)", "200", str(s), s == 200)
    s, _, _, _ = c.solicitar("POST", "/api/v1/clasificar", crudo=b'{"texto": "' + b"x" * 70_000 + b'"}')
    reg.agregar("E-14", "Casos extremos", "Cuerpo de 70 KB (máximo 64 KB)", "413", str(s), s == 413)

    nutr = [("E-15", "Nutrimento negativo (grasa −1 g)", {"grasa_g": -1}),
            ("E-16", "Sodio fuera de rango (50 000 mg)", {"sodio_mg": 50000}),
            ("E-17", "Masa imposible (grasa 80 g + proteína 40 g)", {"grasa_g": 80, "proteina_g": 40}),
            ("E-18", "Estado físico inválido", {"estado_fisico": "gaseoso"})]
    for id_, desc, datos in nutr:
        s, _, _, _ = c.solicitar("POST", "/api/v1/analizar-etiqueta", {"claims": ["Bajo en grasa"], "datos_nutrimentales": datos})
        reg.agregar(id_, "Casos extremos", desc, "422", str(s), s == 422)

    for id_, valor, esperado in [("E-19", 3.0, "CUMPLE"), ("E-20", 3.01, "NO_CUMPLE")]:
        s, r, _, _ = c.solicitar("POST", "/api/v1/analizar-etiqueta",
                                 {"claims": ["Bajo en grasa"], "datos_nutrimentales": {"grasa_g": valor}})
        v = r["resultados"][0]["regla"]["veredicto_propuesto"] if s == 200 else "-"
        reg.agregar(id_, "Casos extremos", f"Límite de regla: «Bajo en grasa» con {valor} g/100 g", esperado, f"{s}, {v}",
                    s == 200 and v == esperado)
    s, r, _, _ = c.solicitar("POST", "/api/v1/analizar-etiqueta",
                             {"claims": ["Alto en proteínas"], "datos_nutrimentales": {"proteina_g": 10, "energia_kcal": 0}})
    v = r["resultados"][0]["regla"]["veredicto_propuesto"] if s == 200 else "-"
    reg.agregar("E-21", "Casos extremos", "Energía 0 kcal en regla de proteína (división entre cero)",
                "200, DATOS_INSUFICIENTES", f"{s}, {v}", s == 200 and v == "DATOS_INSUFICIENTES")

    s1, r1, _, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": "Sin azúcares añadidos"})
    s2, r2, _, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": "SIN AZUCARES ANADIDOS"})
    s3, r3, _, _ = c.solicitar("POST", "/api/v1/clasificar",
                               {"texto": unicodedata.normalize("NFD", "Sin azúcares añadidos")})
    mismas = s1 == s2 == s3 == 200 and r1["probabilidades"] == r2["probabilidades"] == r3["probabilidades"]
    reg.agregar("E-22", "Casos extremos", "Mayúsculas, sin acentos y Unicode descompuesto (NFD)",
                "Misma predicción en las 3 variantes", f"{'idénticas' if mismas else 'distintas'}: {r1.get('categoria')}", mismas)

    atipicos = [("E-23", "Solo emojis", "🍎🍎🍎"), ("E-24", "Solo números", "123456"),
                ("E-25", "Inyección HTML/JS", "<script>alert(1)</script>"),
                ("E-26", "Inyección SQL", "'; DROP TABLE claims;--"),
                ("E-27", "Claim en inglés (fuera del alcance)", "Gluten free"),
                ("E-28", "Texto fuera del dominio", "El cielo es azul")]
    for id_, desc, texto in atipicos:
        s, r, _, _ = c.solicitar("POST", "/api/v1/clasificar", {"texto": texto})
        ok = s == 200 and r.get("texto") == texto
        obt = (f"{s}, {r.get('categoria')} conf {r.get('confianza')}, "
               f"{'a confirmar' if r.get('requiere_confirmacion') else 'sin marca'}") if s == 200 else str(s)
        reg.agregar(id_, "Casos extremos", desc, "200, texto devuelto sin interpretar (sin error 500)", obt, ok)

    s, _, _, _ = c.solicitar("GET", "/api/v1/no-existe")
    reg.agregar("E-29", "Casos extremos", "Ruta inexistente", "404", str(s), s == 404)
    s, _, _, _ = c.solicitar("GET", "/api/v1/clasificar")
    reg.agregar("E-30", "Casos extremos", "Método no permitido (GET en endpoint POST)", "405", str(s), s == 405)


# ── P · Rendimiento ─────────────────────────────────────────────────────────────
def rendimiento(c: Cliente, reg: Registro, n_seq: int, n_conc: int, hilos: int) -> dict:
    print("\nP · Rendimiento")
    textos = ["Sin gluten", "Fuente de fibra", "Receta tradicional", "Ayuda a mantener los huesos", "Bajo en sodio"]
    for _ in range(5):  # calentamiento
        c.solicitar("POST", "/api/v1/clasificar", {"texto": "calentamiento"})
    lat = []
    for i in range(n_seq):
        s, _, _, ms = c.solicitar("POST", "/api/v1/clasificar", {"texto": textos[i % len(textos)]})
        if s == 200:
            lat.append(ms)
    p50, p95, maximo = percentil(lat, 50), percentil(lat, 95), max(lat)
    reg.agregar("P-01", "Rendimiento", f"Latencia secuencial de /clasificar ({n_seq} solicitudes)",
                "p95 ≤ 300 ms (umbral de la Actividad 4)", f"p50 {p50:.1f} ms · p95 {p95:.1f} ms · máx {maximo:.1f} ms",
                len(lat) == n_seq and p95 <= 300)

    def una(i):
        return c.solicitar("POST", "/api/v1/clasificar", {"texto": textos[i % len(textos)]})

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        res = list(ex.map(una, range(n_conc)))
    dur = time.perf_counter() - inicio
    errores = sum(r[0] != 200 for r in res)
    lat_c = [r[3] for r in res]
    rps = n_conc / dur
    reg.agregar("P-02", "Rendimiento", f"Concurrencia: {n_conc} solicitudes con {hilos} hilos",
                "0 errores", f"{errores} errores · {rps:.0f} solicitudes/s · p95 {percentil(lat_c, 95):.0f} ms", errores == 0)

    lote = [textos[i % len(textos)] for i in range(50)]
    lat_l = [c.solicitar("POST", "/api/v1/clasificar/lote", {"claims": lote})[3] for _ in range(20)]
    reg.agregar("P-03", "Rendimiento", "Lote de 50 claims (20 repeticiones)", "Métrica (se reporta)",
                f"mediana {statistics.median(lat_l):.1f} ms → {statistics.median(lat_l) / 50:.2f} ms por claim", True)
    return {"secuencial": {"n": n_seq, "p50_ms": round(p50, 2), "p95_ms": round(p95, 2), "max_ms": round(maximo, 2),
                           "media_ms": round(statistics.mean(lat), 2), "latencias_ms": [round(x, 3) for x in lat]},
            "concurrencia": {"n": n_conc, "hilos": hilos, "errores": errores, "segundos": round(dur, 3),
                             "solicitudes_por_segundo": round(rps, 1), "p50_ms": round(percentil(lat_c, 50), 2),
                             "p95_ms": round(percentil(lat_c, 95), 2)},
            "lote_50": {"repeticiones": 20, "mediana_ms": round(statistics.median(lat_l), 2),
                        "ms_por_claim": round(statistics.median(lat_l) / 50, 3)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--etiqueta", default="local", help="nombre de la corrida (local, render, cloud-run…)")
    ap.add_argument("--salida", default=None, help="ruta del JSON de resultados")
    ap.add_argument("--n-latencia", type=int, default=200)
    ap.add_argument("--n-concurrencia", type=int, default=400)
    ap.add_argument("--hilos", type=int, default=16)
    args = ap.parse_args()
    try:  # consolas de Windows sin UTF-8: evita UnicodeEncodeError con ✔/✘
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    salida = Path(args.salida or RAIZ / "resultados" / f"validacion_{args.etiqueta}.json")

    c = Cliente(args.url)
    reg = Registro()
    print(f"Validando {c.url}  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    info = disponibilidad(c, reg)
    funcionales(c, reg)
    repro = reproducibilidad(c, reg, info)
    extremos(c, reg)
    rend = rendimiento(c, reg, args.n_latencia, args.n_concurrencia, args.hilos)

    grupos = {}
    for p in reg.pruebas:
        g = grupos.setdefault(p["grupo"], {"total": 0, "aprobadas": 0})
        g["total"] += 1
        g["aprobadas"] += p["estado"] == "APROBADA"
    aprobadas = sum(p["estado"] == "APROBADA" for p in reg.pruebas)
    resultado = {
        "meta": {"url": c.url, "etiqueta": args.etiqueta, "fecha": datetime.now().isoformat(timespec="seconds"),
                 "cliente": f"Python {platform.python_version()} · {platform.system()}",
                 "version_modelo": info.get("version_modelo"), "umbral_confianza": info.get("umbral_confianza")},
        "resumen": {"total": len(reg.pruebas), "aprobadas": aprobadas, "fallidas": len(reg.pruebas) - aprobadas,
                    "por_grupo": grupos},
        "reproducibilidad": repro, "rendimiento": rend, "pruebas": reg.pruebas,
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        mostrado = salida.resolve().relative_to(RAIZ)
    except ValueError:
        mostrado = salida
    print(f"\nResultado: {aprobadas}/{len(reg.pruebas)} pruebas aprobadas · detalle en {mostrado}")
    return 0 if aprobadas == len(reg.pruebas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
