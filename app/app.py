"""Conforme: revisa la factura de un proveedor contra la orden de compra y la guía antes de pagar.

    streamlit run app/app.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.cruce import AMBAR, ROJO, VERDE, cruzar  # noqa: E402
from core.extraccion import Documento, extraer  # noqa: E402
from core.lectura import EXT_IMAGEN, leer  # noqa: E402
from core.proveedores import consultar, consultar_lote, datos_disponibles  # noqa: E402

EJEMPLOS = RAIZ / "data" / "ejemplos"
COLOR = {VERDE: "#1a7f37", AMBAR: "#b26b00", ROJO: "#c62828"}
ICONO = {VERDE: "✅", AMBAR: "⚠️", ROJO: "⛔"}

st.set_page_config(page_title="Conforme · control de facturas de proveedores para constructoras", page_icon="🧾", layout="wide")


def ocr_disponible() -> bool:
    try:
        import paddleocr  # noqa: F401
        return True
    except ImportError:
        return False


@st.cache_data(show_spinner=False)
def leer_extraer(contenido: bytes, nombre: str, tipo: str) -> dict:
    sufijo = Path(nombre).suffix.lower() or ".pdf"
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / f"doc{sufijo}"
        ruta.write_bytes(contenido)
        doc = extraer(leer(ruta), tipo=tipo)
    return doc.a_dict()


def a_documento(d: dict) -> Documento:
    from core.extraccion import Item

    d = dict(d)
    d["items"] = [Item(**i) for i in d["items"]]
    return Documento(**d)


def soles(x: float | None) -> str:
    return "—" if x is None else f"S/ {x:,.2f}"


if "historial" not in st.session_state:
    st.session_state.historial = []

# ---------------------------------------------------------------- encabezado
st.title("🧾 Conforme")
st.markdown("#### Control de facturas de proveedores para constructoras")
st.markdown("**Revisamos las facturas de tus proveedores contra la orden de compra y la guía de remisión, y verificamos el RUC en la SUNAT y el OSCE, antes de que pagues.**")
disp = datos_disponibles()
if not all(disp.values()):
    st.warning("Faltan los datos públicos. Corre `python scripts/actualizar_datos.py` para bajar el padrón de la SUNAT y las sanciones del OSCE.")

tab_revisar, tab_prov, tab_panel = st.tabs(["1 · Revisar una factura", "2 · Verificar proveedores", "3 · Panel"])

# ---------------------------------------------------------------- 1. revisar
with tab_revisar:
    casos = json.loads((EJEMPLOS / "casos.json").read_text(encoding="utf-8")) if (EJEMPLOS / "casos.json").exists() else []
    modo = st.radio("Documentos", ["Usar un caso de ejemplo", "Subir mis documentos"], horizontal=True)
    archivos: dict[str, tuple[bytes, str] | None] = {"factura": None, "orden_compra": None, "guia": None}

    if modo == "Usar un caso de ejemplo" and casos:
        etiquetas = {f"{c['titulo']} ({c['caso'].split('_')[1]})": c for c in casos}
        elegido = etiquetas[st.selectbox("Caso", list(etiquetas))]
        carpeta = EJEMPLOS / elegido["caso"]
        usar_foto = st.toggle("Usar la foto de la factura (PaddleOCR)", value=False, disabled=not ocr_disponible(),
                              help="Lee la factura desde una foto en vez del PDF." + ("" if ocr_disponible() else " PaddleOCR no está instalado aquí."))
        nombre_f = "factura_foto.png" if usar_foto else "factura.pdf"
        archivos["factura"] = ((carpeta / nombre_f).read_bytes(), nombre_f)
        archivos["orden_compra"] = ((carpeta / "orden_compra.pdf").read_bytes(), "orden_compra.pdf")
        archivos["guia"] = ((carpeta / "guia_remision.pdf").read_bytes(), "guia_remision.pdf")
        c1, c2, c3 = st.columns(3)
        for col, (k, titulo) in zip((c1, c2, c3), [("factura", "Factura"), ("orden_compra", "Orden de compra"), ("guia", "Guía de remisión")]):
            with col:
                st.caption(f"📄 {titulo}: `{archivos[k][1]}`")
                st.download_button("Ver documento", archivos[k][0], file_name=archivos[k][1], key=f"dl_{k}")
        if usar_foto:
            st.image(archivos["factura"][0], caption="Foto de la factura", width=420)
    else:
        tipos_f = ["pdf"] + ([e.strip(".") for e in EXT_IMAGEN] if ocr_disponible() else [])
        c1, c2, c3 = st.columns(3)
        with c1:
            f = st.file_uploader("Factura (PDF o foto)", type=tipos_f)
        with c2:
            o = st.file_uploader("Orden de compra (PDF)", type=["pdf"])
        with c3:
            g = st.file_uploader("Guía de remisión (PDF)", type=["pdf"])
        for k, up in (("factura", f), ("orden_compra", o), ("guia", g)):
            if up is not None:
                archivos[k] = (up.getvalue(), up.name)
        st.caption("No subas documentos con datos personales de terceros sin permiso. Los archivos no se guardan.")

    if st.button("Revisar", type="primary", disabled=archivos["factura"] is None):
        with st.spinner("Leyendo los documentos y consultando la SUNAT y el OSCE..."):
            docs = {k: a_documento(leer_extraer(v[0], v[1], k)) if v else None for k, v in archivos.items()}
            fac = docs["factura"]
            ficha = consultar(fac.ruc_emisor) if fac.ruc_emisor else None
            res = cruzar(fac, docs["orden_compra"], docs["guia"], ficha)
        st.session_state.ultimo = (docs, ficha, res)
        st.session_state.historial.append({
            "hora": datetime.now().strftime("%H:%M:%S"),
            "proveedor": (ficha.razon_social if ficha and ficha.encontrado else fac.razon_social) or fac.ruc_emisor,
            "ruc": fac.ruc_emisor,
            "factura": fac.numero,
            "total": res.total_factura or 0.0,
            "a_retener": res.a_retener,
            "resultado": res.nivel,
            "temas": sorted({a.tema for a in res.alertas}),
        })

    if "ultimo" in st.session_state:
        docs, ficha, res = st.session_state.ultimo
        fac = docs["factura"]
        st.markdown(
            f"<div style='padding:14px 18px;border-radius:10px;background:{COLOR[res.nivel]}1a;border-left:6px solid {COLOR[res.nivel]}'>"
            f"<span style='font-size:1.4rem;font-weight:700;color:{COLOR[res.nivel]}'>{ICONO[res.nivel]} {res.veredicto}</span></div>",
            unsafe_allow_html=True,
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Factura", fac.numero or "—", fac.fecha)
        m2.metric("Total facturado", soles(res.total_factura))
        m3.metric("Corresponde pagar", soles(res.total_correcto))
        m4.metric("Retener hasta aclarar", soles(res.a_retener))

        izq, der = st.columns([3, 2])
        with izq:
            st.subheader("Observaciones")
            if not res.alertas:
                st.success("Los tres documentos cuadran y el proveedor no tiene alertas.")
            for a in sorted(res.alertas, key=lambda a: a.nivel != ROJO):
                st.markdown(f"{ICONO[a.nivel]} **{a.tema}.** {a.mensaje}")
            st.subheader("Cruce ítem por ítem")
            if res.filas:
                df = pd.DataFrame([vars(f) for f in res.filas]).rename(columns={
                    "descripcion": "Descripción", "codigo": "Código", "cant_oc": "Cant. OC", "cant_guia": "Cant. guía",
                    "cant_factura": "Cant. factura", "precio_oc": "Precio OC", "precio_factura": "Precio factura",
                    "importe_factura": "Importe factura", "importe_correcto": "Importe correcto", "estado": "Estado"})
                st.dataframe(df, hide_index=True, use_container_width=True)
        with der:
            st.subheader("Proveedor")
            if ficha is None:
                st.info("No se encontró el RUC en la factura.")
            else:
                st.markdown(f"**{ficha.razon_social or fac.razon_social}**  \nRUC `{ficha.ruc}`")
                if ficha.encontrado:
                    ok = ficha.activo_habido
                    st.markdown(f"SUNAT: {'🟢' if ok else '🔴'} {ficha.estado} · {ficha.condicion}")
                else:
                    st.markdown("SUNAT: 🟡 no aparece en el padrón de personas jurídicas")
                sv = ficha.sancion_vigente
                st.markdown(f"OSCE: {'🔴 inhabilitación vigente' if sv else ('🟡 sanciones pasadas o multas' if ficha.sanciones else '🟢 sin sanciones')}")
                if ficha.sanciones:
                    st.dataframe(pd.DataFrame([vars(s) for s in ficha.sanciones])[["tipo", "inicio", "fin", "resolucion", "vigente"]],
                                 hide_index=True, use_container_width=True)
                st.caption("Fuentes: padrón reducido de RUC de la SUNAT y proveedores sancionados del Tribunal de Contrataciones del Estado (datos abiertos)."
                           + (f" Corte del OSCE: {ficha.corte_osce}." if ficha.corte_osce else ""))
            with st.expander("Lo que se leyó de cada documento"):
                for k, d in docs.items():
                    if d:
                        st.markdown(f"**{k.replace('_', ' ').capitalize()}** · leído por {'OCR' if d.metodo == 'ocr' else 'texto del PDF'}"
                                    + (f" (confianza {d.confianza:.0%})" if d.metodo == "ocr" else ""))
                        st.json({x: y for x, y in d.a_dict().items() if x not in ("metodo", "confianza")}, expanded=False)

# ---------------------------------------------------------------- 2. proveedores
with tab_prov:
    st.markdown("Pega los RUC de tus proveedores (uno por línea) o sube un CSV con una columna `ruc`. Se revisan contra el padrón de la SUNAT y las sanciones del OSCE.")
    texto = st.text_area("RUC", "20123531389\n20126015900\n20568769792\n20101571701", height=130)
    csv = st.file_uploader("o un CSV", type=["csv"], key="csv_prov")
    rucs = [r for r in texto.split() if r.strip()]
    if csv is not None:
        tabla = pd.read_csv(csv, dtype=str)
        col = next((c for c in tabla.columns if c.lower().strip() == "ruc"), tabla.columns[0])
        rucs = tabla[col].dropna().tolist()
    if st.button("Verificar", key="verificar"):
        fichas = consultar_lote(rucs)
        filas = []
        for f in fichas:
            sv = f.sancion_vigente
            alerta = (not f.valido) or (f.encontrado and not f.activo_habido) or sv is not None
            filas.append({
                "": "🔴" if alerta else ("🟡" if (not f.encontrado or f.sanciones) else "🟢"),
                "RUC": f.ruc, "Razón social": f.razon_social or ("RUC inválido" if not f.valido else "no encontrado"),
                "Estado SUNAT": f.estado, "Condición": f.condicion,
                "OSCE": f"inhabilitado hasta {sv.fin}" if sv else (f"{len(f.sanciones)} sanción(es) pasada(s)" if f.sanciones else "sin sanciones"),
            })
        df = pd.DataFrame(filas)
        st.dataframe(df, hide_index=True, use_container_width=True)
        rojos = (df[""] == "🔴").sum()
        st.markdown(f"**{rojos} de {len(df)}** proveedores tienen una alerta que impide pagar sin revisar.")
        st.download_button("Descargar resultado (CSV)", df.to_csv(index=False).encode("utf-8"), "proveedores_verificados.csv", "text/csv")

# ---------------------------------------------------------------- 3. panel
with tab_panel:
    h = st.session_state.historial
    if st.button("Cargar los 3 casos de ejemplo al panel"):
        for c in casos:
            d = EJEMPLOS / c["caso"]
            fac = a_documento(leer_extraer((d / "factura.pdf").read_bytes(), "factura.pdf", "factura"))
            oc = a_documento(leer_extraer((d / "orden_compra.pdf").read_bytes(), "orden_compra.pdf", "orden_compra"))
            gu = a_documento(leer_extraer((d / "guia_remision.pdf").read_bytes(), "guia_remision.pdf", "guia"))
            fi = consultar(fac.ruc_emisor)
            r = cruzar(fac, oc, gu, fi)
            h.append({"hora": datetime.now().strftime("%H:%M:%S"), "proveedor": fi.razon_social or fac.razon_social, "ruc": fac.ruc_emisor,
                      "factura": fac.numero, "total": r.total_factura or 0.0, "a_retener": r.a_retener, "resultado": r.nivel,
                      "temas": sorted({a.tema for a in r.alertas})})
    if not h:
        st.info("Todavía no hay facturas revisadas en esta sesión.")
    else:
        df = pd.DataFrame(h)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Facturas revisadas", len(df))
        k2.metric("Monto revisado", soles(df["total"].sum()))
        k3.metric("Retenido por descuadres", soles(df["a_retener"].sum()))
        k4.metric("Con observaciones", f"{(df['resultado'] != VERDE).sum()} de {len(df)}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Observaciones por tema**")
            temas = df.explode("temas")["temas"].dropna().value_counts()
            if len(temas):
                st.bar_chart(temas)
        with c2:
            st.markdown("**Resultado de las revisiones**")
            st.bar_chart(df["resultado"].value_counts())
        st.dataframe(df.assign(temas=df["temas"].str.join(", ")), hide_index=True, use_container_width=True)
        st.download_button("Descargar historial (CSV)", df.to_csv(index=False).encode("utf-8"), "historial_conforme.csv", "text/csv")

st.divider()
st.caption("Conforme · demo del proyecto final de la Diplomatura en Ciencia de Datos para las Ciencias Sociales y la Gestión Pública (PUCP). "
           "Los documentos de ejemplo son sintéticos y no tienen valor tributario; los datos de la SUNAT y el OSCE son públicos y reales.")
