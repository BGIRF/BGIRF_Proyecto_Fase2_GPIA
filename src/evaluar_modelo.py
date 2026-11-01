"""Figuras de evaluación del modelo y de la validación del contenedor.

Uso (desde la raíz del repositorio):
    pip install -r requirements-analisis.txt
    python -m src.evaluar_modelo

Lee los metadatos del modelo (modelos/*.json) y, si existen, los resultados de
scripts/validar_contenedor.py (resultados/validacion_*.json). Escribe en resultados/figuras/.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FIG = RAIZ / "resultados" / "figuras"
AZUL, NARANJA, GRIS = "#2a78d6", "#eb6834", "#b8b6ae"
TINTA, TINTA_2, REJILLA = "#1f1f1d", "#52514e", "#e6e5e0"
SECUENCIAL = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": REJILLA, "axes.labelcolor": TINTA_2,
    "xtick.color": TINTA_2, "ytick.color": TINTA_2, "axes.titleweight": "bold", "axes.titlesize": 11,
    "axes.titlecolor": TINTA, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150,
    "savefig.bbox": "tight", "savefig.facecolor": "white",
})


def comparacion_actividad4(meta: dict) -> None:
    ref = meta["referencia_actividad4_zero_shot"]
    g = meta["metricas_prueba"]["globales"]
    modelos = ["TF-IDF + RegLog\n(Fase 2, supervisado)"] + [f"{k}\n(zero-shot, Act. 4)" for k in ref]
    paneles = [("Macro-F1", [g["f1_macro"]] + [v["f1_macro"] for v in ref.values()], 0.80),
               ("Recall de SALUD", [g["recall_salud"]] + [v["recall_salud"] for v in ref.values()], 0.90)]
    fig, ejes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    y = np.arange(len(modelos))[::-1]
    for ax, (titulo, valores, umbral) in zip(ejes, paneles):
        colores = [AZUL] + [GRIS] * (len(valores) - 1)
        ax.barh(y, valores, color=colores, height=0.55, edgecolor="white", linewidth=2)
        for yi, v in zip(y, valores):
            ax.text(v - 0.02, yi, f"{v:.2f}", va="center", ha="right", fontsize=9.5, color="white", fontweight="bold")
        ax.axvline(umbral, color=TINTA_2, ls="--", lw=1)
        ax.set_xlim(0, 1.02)
        ax.tick_params(axis="y", length=0)
        ax.set_title(f"{titulo}  (umbral {umbral:.2f}, línea punteada)", loc="left")
        ax.grid(axis="x", color=REJILLA, lw=0.8)
        ax.set_axisbelow(True)
    ejes[0].set_yticks(y, modelos)
    fig.suptitle("Mismo conjunto de prueba (169 claims): supervisado frente a zero-shot", x=0.01, ha="left",
                 fontsize=11.5, fontweight="bold", color=TINTA)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_comparacion_actividad4.png")
    plt.close(fig)


def matriz_confusion(meta: dict) -> None:
    mc = meta["metricas_prueba"]["matriz_confusion"]
    clases, m = mc["clases"], np.array(mc["valores"])
    fig, ax = plt.subplots(figsize=(5.4, 4.4))
    cmap = LinearSegmentedColormap.from_list("azul", SECUENCIAL)
    ax.imshow(m, cmap=cmap, vmin=0, vmax=m.max())
    for i in range(len(clases)):
        for j in range(len(clases)):
            ax.text(j, i, m[i, j], ha="center", va="center", fontsize=11,
                    color="white" if m[i, j] > m.max() * 0.55 else TINTA, fontweight="bold" if i == j else None)
    ax.set_xticks(range(len(clases)), clases, rotation=20)
    ax.set_yticks(range(len(clases)), clases)
    ax.set_xlabel("Categoría propuesta por el modelo")
    ax.set_ylabel("Categoría real")
    ax.set_title("Matriz de confusión · conjunto de prueba", loc="left")
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(FIG / "fig2_matriz_confusion.png")
    plt.close(fig)


def curva_tau(meta: dict) -> None:
    curva = [p for p in meta["metricas_prueba"]["curva_tau"] if p["exactitud_auto"] is not None]
    tau = meta["umbral_confianza"]["valor"]
    t = [p["tau"] for p in curva]
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    ax.plot(t, [p["cobertura"] for p in curva], color=AZUL, lw=2, marker="o", ms=5, label="Cobertura (se enruta sin confirmar)")
    ax.plot(t, [p["exactitud_auto"] for p in curva], color=NARANJA, lw=2, marker="s", ms=5,
            label="Exactitud de lo que se enruta sin confirmar")
    ax.axvline(tau, color=TINTA_2, ls="--", lw=1)
    ax.text(tau + 0.008, 0.30, f"τ = {tau:.2f}\n(elegido en dev)", fontsize=8.5, color=TINTA_2)
    ax.axhline(0.90, color=REJILLA, lw=1)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Umbral de confianza τ")
    ax.set_title("Cobertura frente a exactitud según el umbral (conjunto de prueba)", loc="left")
    ax.grid(color=REJILLA, lw=0.8)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8.5)
    fig.savefig(FIG / "fig3_cobertura_vs_tau.png")
    plt.close(fig)


def latencias() -> None:
    corridas = [("Local · 0.5 CPU, 512 MB", RAIZ / "resultados" / "validacion_local.json"),
                ("Simulación Render Free · 0.1 CPU, 512 MB", RAIZ / "resultados" / "validacion_simulacion_render_free.json")]
    datos = [(n, json.loads(p.read_text(encoding="utf-8"))["rendimiento"]) for n, p in corridas if p.exists()]
    if not datos:
        return
    fig, ax = plt.subplots(figsize=(7.4, 2.9))
    etiquetas = [n for n, _ in datos]
    y = np.arange(len(datos))[::-1]
    p50 = [r["secuencial"]["p50_ms"] for _, r in datos]
    p95 = [r["secuencial"]["p95_ms"] for _, r in datos]
    ax.barh(y + 0.17, p50, height=0.32, color=AZUL, edgecolor="white", linewidth=2, label="p50")
    ax.barh(y - 0.17, p95, height=0.32, color=NARANJA, edgecolor="white", linewidth=2, label="p95")
    for yi, a, b in zip(y, p50, p95):
        ax.text(a + 4, yi + 0.17, f"{a:.1f} ms", va="center", fontsize=8.5, color=TINTA)
        ax.text(b + 4, yi - 0.17, f"{b:.1f} ms", va="center", fontsize=8.5, color=TINTA)
    ax.axvline(300, color=TINTA_2, ls="--", lw=1)
    ax.set_yticks(y, etiquetas)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 330)
    ax.set_xlabel("Latencia por solicitud de /api/v1/clasificar (ms)")
    ax.set_title("Latencia contra el contenedor en ejecución (umbral 300 ms, línea punteada)", loc="left")
    ax.grid(axis="x", color=REJILLA, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    fig.savefig(FIG / "fig4_latencias.png")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    meta = json.loads((RAIZ / "modelos" / "claimcheck_router_v1.json").read_text(encoding="utf-8"))
    comparacion_actividad4(meta)
    matriz_confusion(meta)
    curva_tau(meta)
    latencias()
    print("Figuras en", FIG.relative_to(RAIZ), [p.name for p in sorted(FIG.glob("*.png"))])


if __name__ == "__main__":
    main()
