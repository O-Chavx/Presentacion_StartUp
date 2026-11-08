"""Genera los documentos de ejemplo del demo: orden de compra, guía de remisión y factura.

Todos son sintéticos y llevan la marca "DOCUMENTO DE PRUEBA - SIN VALOR TRIBUTARIO".
El comprador es una constructora ficticia. Los proveedores usan RUC reales del padrón
público de la SUNAT para que la verificación del RUC se haga con datos reales.

Uso:
    python scripts/generar_ejemplos.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF, para pasar la factura a imagen (la "foto")
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "data" / "ejemplos"

COMPRADOR = {"ruc": "20000000001", "razon_social": "CONSTRUCTORA EJEMPLO S.A.C."}
OBRA = "Obra: Restauración de fachada - Jr. Ejemplo 123, Lima"
IGV = 0.18


@dataclass
class Item:
    codigo: str
    descripcion: str
    unidad: str
    cantidad: float
    precio: float  # valor unitario sin IGV


@dataclass
class Caso:
    nombre: str
    titulo: str
    proveedor_ruc: str
    proveedor_nombre: str
    oc_numero: str
    guia_numero: str
    factura_numero: str
    fecha: str
    oc: list[Item]
    guia: list[Item]  # lo que llegó a obra (precio no se usa)
    factura: list[Item]
    notas: list[str] = field(default_factory=list)


def total(items: list[Item]) -> tuple[float, float, float]:
    sub = round(sum(round(i.cantidad * i.precio, 2) for i in items), 2)
    igv = round(sub * IGV, 2)
    return sub, igv, round(sub + igv, 2)


def marca_prueba(c: canvas.Canvas) -> None:
    c.saveState()
    c.setFont("Helvetica-Bold", 34)
    c.setFillGray(0.88)
    c.translate(105 * mm, 140 * mm)
    c.rotate(35)
    c.drawCentredString(0, 0, "DOCUMENTO DE PRUEBA")
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(0, -12 * mm, "SIN VALOR TRIBUTARIO")
    c.restoreState()


def tabla(c: canvas.Canvas, y: float, items: list[Item], con_precio: bool) -> float:
    c.setFont("Helvetica-Bold", 9)
    cols = [15, 35, 55, 125, 150, 175] if con_precio else [15, 35, 55, 150]
    head = ["CANT.", "UNID.", "DESCRIPCIÓN", "CÓDIGO", "V. UNIT.", "IMPORTE"] if con_precio else ["CANT.", "UNID.", "DESCRIPCIÓN", "CÓDIGO"]
    for x, h in zip(cols, head):
        c.drawString(x * mm, y, h)
    c.line(15 * mm, y - 2 * mm, 195 * mm, y - 2 * mm)
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for i in items:
        vals = [f"{i.cantidad:,.2f}", i.unidad, i.descripcion, i.codigo]
        if con_precio:
            vals += [f"{i.precio:,.2f}", f"{i.cantidad * i.precio:,.2f}"]
        for x, v in zip(cols, vals):
            c.drawString(x * mm, y, v)
        y -= 6 * mm
    c.line(15 * mm, y + 2 * mm, 195 * mm, y + 2 * mm)
    return y - 4 * mm


def totales(c: canvas.Canvas, y: float, items: list[Item]) -> None:
    sub, igv, tot = total(items)
    c.setFont("Helvetica", 10)
    for etiqueta, v in [("OP. GRAVADA S/", sub), ("IGV 18% S/", igv), ("IMPORTE TOTAL S/", tot)]:
        c.drawRightString(170 * mm, y, etiqueta)
        c.drawRightString(195 * mm, y, f"{v:,.2f}")
        y -= 6 * mm


def orden_compra(caso: Caso, ruta: Path) -> None:
    c = canvas.Canvas(str(ruta), pagesize=A4)
    marca_prueba(c)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, 280 * mm, COMPRADOR["razon_social"])
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, 274 * mm, f"RUC: {COMPRADOR['ruc']}")
    c.drawString(15 * mm, 268 * mm, OBRA)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(195 * mm, 280 * mm, "ORDEN DE COMPRA")
    c.drawRightString(195 * mm, 273 * mm, f"N° {caso.oc_numero}")
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, 255 * mm, f"Proveedor: {caso.proveedor_nombre}")
    c.drawString(15 * mm, 249 * mm, f"RUC del proveedor: {caso.proveedor_ruc}")
    c.drawString(15 * mm, 243 * mm, f"Fecha: {caso.fecha}")
    y = tabla(c, 230 * mm, caso.oc, con_precio=True)
    totales(c, y, caso.oc)
    c.drawString(15 * mm, 40 * mm, "Aprobado por: Jefatura de Logística")
    c.save()


def guia(caso: Caso, ruta: Path) -> None:
    c = canvas.Canvas(str(ruta), pagesize=A4)
    marca_prueba(c)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, 280 * mm, caso.proveedor_nombre)
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, 274 * mm, f"RUC: {caso.proveedor_ruc}")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(195 * mm, 280 * mm, "GUÍA DE REMISIÓN REMITENTE")
    c.drawRightString(195 * mm, 273 * mm, caso.guia_numero)
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, 255 * mm, f"Destinatario: {COMPRADOR['razon_social']}  RUC: {COMPRADOR['ruc']}")
    c.drawString(15 * mm, 249 * mm, f"Punto de llegada: {OBRA.removeprefix('Obra: ')}")
    c.drawString(15 * mm, 243 * mm, f"Fecha de traslado: {caso.fecha}   Orden de compra: {caso.oc_numero}")
    y = tabla(c, 230 * mm, caso.guia, con_precio=False)
    c.drawString(15 * mm, y - 10 * mm, "Recibido conforme en obra: ____________________  (residente de obra)")
    c.save()


def factura(caso: Caso, ruta: Path) -> None:
    c = canvas.Canvas(str(ruta), pagesize=A4)
    marca_prueba(c)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, 280 * mm, caso.proveedor_nombre)
    c.rect(130 * mm, 262 * mm, 65 * mm, 24 * mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(162.5 * mm, 280 * mm, f"RUC {caso.proveedor_ruc}")
    c.drawCentredString(162.5 * mm, 273 * mm, "FACTURA ELECTRÓNICA")
    c.drawCentredString(162.5 * mm, 266 * mm, caso.factura_numero)
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, 250 * mm, f"Fecha de emisión: {caso.fecha}")
    c.drawString(15 * mm, 244 * mm, f"Señor(es): {COMPRADOR['razon_social']}")
    c.drawString(15 * mm, 238 * mm, f"RUC: {COMPRADOR['ruc']}")
    c.drawString(15 * mm, 232 * mm, f"Orden de compra: {caso.oc_numero}   Guía de remisión: {caso.guia_numero}")
    c.drawString(15 * mm, 226 * mm, "Moneda: SOLES")
    y = tabla(c, 214 * mm, caso.factura, con_precio=True)
    totales(c, y, caso.factura)
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, 20 * mm, "Representación impresa de la factura electrónica (EJEMPLO, sin validez).")
    c.save()


def a_foto(pdf: Path, png: Path) -> None:
    """Simula una foto: rasteriza a 150 dpi y la gira un poco."""
    doc = fitz.open(pdf)
    pix = doc[0].get_pixmap(dpi=150)
    pix.save(png)
    doc.close()
    try:
        from PIL import Image, ImageFilter

        im = Image.open(png).convert("L").rotate(1.2, expand=True, fillcolor=235)
        im = im.filter(ImageFilter.GaussianBlur(0.6))
        im.save(png)
    except ImportError:
        pass


def casos(proveedores: dict[str, dict]) -> list[Caso]:
    p1, p2, p3 = proveedores["ok"], proveedores["descuadre"], proveedores["riesgo"]
    base = [
        Item("CEM-01", "CEMENTO PORTLAND TIPO I X 42.5 KG", "BOL", 100, 28.50),
        Item("FIE-12", "FIERRO CORRUGADO 1/2\" X 9 M", "VAR", 60, 39.90),
        Item("ALA-16", "ALAMBRE NEGRO RECOCIDO N 16", "KG", 25, 6.20),
    ]
    pintura = [
        Item("PIN-LT", "PINTURA LATEX EXTERIOR BLANCO X 4 GL", "BAL", 12, 185.00),
        Item("IMP-01", "IMPRIMANTE X 4 GL", "BAL", 6, 72.00),
    ]
    electricos = [
        Item("CAB-14", "CABLE THW 14 AWG X 100 M", "ROL", 8, 165.00),
        Item("TUB-34", "TUBO PVC SAP ELECTRICO 3/4\" X 3 M", "UND", 40, 4.80),
    ]
    return [
        Caso(
            "caso_1_cuadra", "Todo cuadra", p1["ruc"], p1["razon_social"],
            "OC-2026-0141", "T001-00004521", "F001-00012877", "03/11/2026",
            oc=base, guia=base, factura=base,
            notas=["La factura, la OC y la guía coinciden."],
        ),
        Caso(
            "caso_2_descuadre", "Cobra de más", p2["ruc"], p2["razon_social"],
            "OC-2026-0147", "T002-00000873", "F002-00003318", "04/11/2026",
            oc=pintura,
            guia=[Item("PIN-LT", "PINTURA LATEX EXTERIOR BLANCO X 4 GL", "BAL", 10, 0), Item("IMP-01", "IMPRIMANTE X 4 GL", "BAL", 6, 0)],
            factura=[Item("PIN-LT", "PINTURA LATEX EXTERIOR BLANCO X 4 GL", "BAL", 12, 198.00), Item("IMP-01", "IMPRIMANTE X 4 GL", "BAL", 6, 72.00)],
            notas=["Facturan 12 baldes y a obra llegaron 10.", "El precio de la pintura sube de 185.00 a 198.00."],
        ),
        Caso(
            "caso_3_riesgo", "Proveedor con alerta", p3["ruc"], p3["razon_social"],
            "OC-2026-0152", "EG01-00000219", "E001-00000457", "05/11/2026",
            oc=electricos, guia=electricos, factura=electricos,
            notas=["Los documentos cuadran, pero el proveedor tiene una alerta en SUNAT u OSCE."],
        ),
    ]


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    proveedores = json.loads((SALIDA / "proveedores.json").read_text(encoding="utf-8"))
    resumen = []
    for caso in casos(proveedores):
        d = SALIDA / caso.nombre
        d.mkdir(exist_ok=True)
        orden_compra(caso, d / "orden_compra.pdf")
        guia(caso, d / "guia_remision.pdf")
        factura(caso, d / "factura.pdf")
        a_foto(d / "factura.pdf", d / "factura_foto.png")
        resumen.append({"caso": caso.nombre, "titulo": caso.titulo, "notas": caso.notas,
                        "proveedor_ruc": caso.proveedor_ruc})
        print(f"{caso.nombre}: listo")
    (SALIDA / "casos.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
