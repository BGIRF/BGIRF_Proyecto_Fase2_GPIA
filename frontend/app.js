// Frontend de ClaimCheck IA: consume la API REST con fetch().
// Por defecto llama al mismo origen que sirve la página. Para usar un backend
// desplegado en otro dominio: index.html?api=https://mi-api.onrender.com
// (y agregar ese origen en ORIGENES_PERMITIDOS del backend).
"use strict";

const API = (new URLSearchParams(location.search).get("api") || "").replace(/\/$/, "");
const $ = (id) => document.getElementById(id);
const CAMPOS = ["energia_kcal", "grasa_g", "azucares_g", "sodio_mg", "fibra_g", "proteina_g"];
const ETIQUETAS_VEREDICTO = {
  CUMPLE: "Cumple", NO_CUMPLE: "No cumple",
  REQUIERE_EVIDENCIA: "Requiere evidencia", DATOS_INSUFICIENTES: "Datos insuficientes",
};
const EJEMPLO = {
  producto: "Cereal integral de avena",
  claims: ["Fuente de fibra", "Bajo en grasa", "Sin azúcares añadidos", "Sin gluten",
           "Receta tradicional", "La fibra de avena contribuye a aumentar el volumen de las heces"],
  datos: { estado_fisico: "solido", energia_kcal: 372, grasa_g: 6.5, azucares_g: 1.2,
           sodio_mg: 8, fibra_g: 9.8, proteina_g: 13.1 },
};

async function llamar(ruta, opciones = {}) {
  const r = await fetch(API + ruta, {
    ...opciones,
    headers: { "Content-Type": "application/json", ...(opciones.headers || {}) },
  });
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(describirError(r.status, cuerpo));
  return cuerpo;
}

function describirError(status, cuerpo) {
  const d = cuerpo && cuerpo.detail;
  if (Array.isArray(d)) {
    return `La API rechazó la solicitud (${status}): ` +
      d.map((e) => `${(e.loc || []).slice(1).join(" › ") || "cuerpo"}: ${e.msg}`).join("; ");
  }
  return `La API respondió ${status}${d ? ": " + d : ""}`;
}

async function verificarEstado() {
  const caja = $("estado");
  try {
    const salud = await llamar("/health");
    const info = await llamar("/api/v1/info");
    caja.className = "estado ok";
    $("estado-texto").textContent = `API en línea · modelo v${salud.version_modelo}`;
    $("pie-modelo").textContent =
      `Modelo ${info.nombre} v${info.version_modelo} · umbral de confianza τ = ${info.umbral_confianza.toFixed(2)}` +
      ` · macro-F1 en prueba ${info.metricas_prueba.f1_macro.toFixed(2)}`;
  } catch (e) {
    caja.className = "estado caido";
    $("estado-texto").textContent = "API no disponible";
  }
}

function leerFormulario() {
  const claims = $("claims").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const form = $("formulario");
  const datos = { estado_fisico: form.estado_fisico.value };
  let hayDatos = false;
  for (const c of CAMPOS) {
    const v = form[c].value.trim();
    if (v !== "") { datos[c] = Number(v); hayDatos = true; }
  }
  const producto = $("producto").value.trim();
  return { producto: producto || null, claims, datos_nutrimentales: hayDatos ? datos : null };
}

function el(etiqueta, clase, texto) {
  const n = document.createElement(etiqueta);
  if (clase) n.className = clase;
  if (texto !== undefined) n.textContent = texto; // textContent: el texto nunca se interpreta como HTML
  return n;
}

function pintar(resp) {
  $("vacio").hidden = true;
  $("resultados").hidden = false;

  const resumen = $("resumen");
  resumen.replaceChildren();
  const tarjetas = [
    [resp.resumen.total_claims, "claims analizados"],
    [resp.resumen.claims_a_confirmar, "enrutamientos a confirmar"],
    [resp.resumen.por_veredicto.CUMPLE || 0, "reglas: cumple"],
    [resp.resumen.por_veredicto.NO_CUMPLE || 0, "reglas: no cumple"],
  ];
  for (const [valor, texto] of tarjetas) {
    const t = el("div", "tarjeta");
    t.append(el("b", "", String(valor)), el("span", "", texto));
    resumen.append(t);
  }

  const filas = $("filas");
  filas.replaceChildren();
  for (const r of resp.resultados) {
    const tr = document.createElement("tr");

    tr.append(el("td", "claim", r.texto));

    const cat = el("td");
    cat.append(el("span", `chip c-${r.categoria}`, r.categoria), el("span", "checklist", r.checklist));
    tr.append(cat);

    const conf = el("td");
    conf.append(el("span", "", `${(r.confianza * 100).toFixed(0)} %`));
    const barra = el("div", "barra-conf");
    const relleno = el("i");
    relleno.style.width = `${Math.round(r.confianza * 100)}%`;
    barra.append(relleno);
    conf.append(barra);
    if (r.requiere_confirmacion) {
      const aviso = el("span", "confirmar", "Confirmar enrutamiento");
      aviso.title = r.motivos.join(" ");
      conf.append(aviso);
    }
    tr.append(conf);

    const regla = el("td");
    if (r.regla) {
      const v = r.regla.veredicto_propuesto;
      regla.append(el("span", `chip v-${v}`, `${r.regla.regla_id} · ${ETIQUETAS_VEREDICTO[v]}`),
                   el("span", "detalle", r.regla.detalle));
    } else {
      regla.append(el("span", "detalle", "Sin regla automática: revisión con el checklist."));
    }
    tr.append(regla);
    filas.append(tr);
  }
  $("json").textContent = JSON.stringify(resp, null, 2);
}

async function analizar(evento) {
  evento.preventDefault();
  const error = $("error");
  error.hidden = true;
  const carga = leerFormulario();
  if (carga.claims.length === 0) {
    error.textContent = "Escribe al menos un claim (uno por línea).";
    error.hidden = false;
    return;
  }
  const boton = $("btn-analizar");
  boton.disabled = true;
  boton.textContent = "Analizando…";
  try {
    pintar(await llamar("/api/v1/analizar-etiqueta", { method: "POST", body: JSON.stringify(carga) }));
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  } finally {
    boton.disabled = false;
    boton.textContent = "Analizar etiqueta";
  }
}

function cargarEjemplo() {
  const form = $("formulario");
  $("producto").value = EJEMPLO.producto;
  $("claims").value = EJEMPLO.claims.join("\n");
  form.estado_fisico.value = EJEMPLO.datos.estado_fisico;
  for (const c of CAMPOS) form[c].value = EJEMPLO.datos[c];
}

function limpiar() {
  $("formulario").reset();
  $("error").hidden = true;
  $("resultados").hidden = true;
  $("vacio").hidden = false;
}

$("formulario").addEventListener("submit", analizar);
$("btn-ejemplo").addEventListener("click", cargarEjemplo);
$("btn-limpiar").addEventListener("click", limpiar);
verificarEstado();
