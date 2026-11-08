"""De las líneas leídas a un documento estructurado: RUC, número, ítems y totales.

Las reglas buscan lo que la SUNAT exige que aparezca en la representación impresa de una
factura electrónica y de una guía de remisión (RUC, serie y número, fecha, importes), y
lo que suele traer una orden de compra. No dependen de un LLM, así el demo corre sin
claves de API.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .lectura import Lectura, Linea

RE_RUC = re.compile(r"\b(?:10|15|16|17|20)\d{9}\b")
RE_FECHA = re.compile(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b")
RE_FACTURA = re.compile(r"\b([FE][A-Z0-9]{3})\s*[-–]\s*(\d{1,8})\b")
RE_GUIA = re.compile(r"\b([TVE][A-Z0-9]{3})\s*[-–]\s*(\d{1,8})\b")
RE_OC = re.compile(r"\bOC[-\s]?\d{2,4}[-\s]?\d{1,6}\b", re.I)
RE_NUM = re.compile(r"^-?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,4})?$|^-?\d+(?:\.\d{1,4})?$|^-?\d+,\d{1,2}$")
RE_CODIGO = re.compile(r"^[A-Z0-9]{2,6}-[A-Z0-9]{1,6}$")
UNIDADES = {
    "UND", "UNID", "NIU", "BOL", "BLS", "VAR", "KG", "KGM", "M", "M2", "M3", "MTQ", "ML", "GL",
    "GLN", "LT", "LTR", "BAL", "ROL", "CJA", "CAJ", "PZA", "PAR", "JGO", "TN", "TNE", "ZZ", "PLG",
}


@dataclass
class Item:
    descripcion: str
    cantidad: float
    unidad: str = ""
    codigo: str = ""
    precio: float | None = None  # valor unitario sin IGV
    importe: float | None = None


@dataclass
class Documento:
    tipo: str  # factura, orden_compra, guia
    ruc_emisor: str = ""
    razon_social: str = ""
    ruc_proveedor: str = ""  # en la OC: a quién se le compra
    numero: str = ""
    fecha: str = ""
    ref_oc: str = ""
    ref_guia: str = ""
    items: list[Item] = field(default_factory=list)
    subtotal: float | None = None
    igv: float | None = None
    total: float | None = None
    metodo: str = ""
    confianza: float = 1.0

    @property
    def ruc_contraparte(self) -> str:
        """El RUC del proveedor, sea quien emite (factura, guía) o a quien se compra (OC)."""
        return self.ruc_proveedor if self.tipo == "orden_compra" else self.ruc_emisor

    def a_dict(self) -> dict:
        return asdict(self)


def numero(texto: str) -> float | None:
    t = texto.replace("S/", "").replace(" ", "").strip()
    if not RE_NUM.match(t):
        return None
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:  # 1,250 (miles) o 12,50 (decimal)
        partes = t.split(",")
        t = t.replace(",", "") if len(partes[-1]) == 3 else t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _ultimo_numero(linea: Linea) -> float | None:
    for t in reversed(linea.textos):
        for pieza in reversed(t.split()):
            v = numero(pieza)
            if v is not None:
                return v
    return None


def detectar_tipo(texto: str) -> str:
    t = texto.upper()
    if "FACTURA ELECTR" in t or re.search(r"\bFACTURA\b", t[:400]):
        return "factura"
    if "REMISI" in t and re.search(r"GU[IÍ]A", t):
        return "guia"
    if "ORDEN DE COMPRA" in t:
        return "orden_compra"
    return "factura"


def _item(linea: Linea, con_precio: bool) -> Item | None:
    celdas = [c.texto.strip() for c in linea.celdas if c.texto.strip()]
    if len(celdas) < 3:
        return None
    cant = numero(celdas[0])
    if cant is None or cant <= 0:
        return None
    resto = celdas[1:]
    nums = [(i, numero(c)) for i, c in enumerate(resto)]
    codigo = next((c for c in resto if RE_CODIGO.match(c)), "")
    unidad = next((c for c in resto if c.upper() in UNIDADES), "")
    textos = [c for i, c in enumerate(resto) if nums[i][1] is None and c not in (codigo, unidad)]
    if not textos:
        return None
    descripcion = max(textos, key=len)
    if len(descripcion) < 3 or descripcion.upper().startswith(("OP.", "IGV", "IMPORTE", "TOTAL")):
        return None
    valores = [v for _, v in nums if v is not None]
    precio = importe = None
    if con_precio and len(valores) >= 2:
        precio, importe = valores[-2], valores[-1]
    elif con_precio and len(valores) == 1:
        importe = valores[0]
        precio = round(importe / cant, 4)
    return Item(descripcion=descripcion, cantidad=cant, unidad=unidad, codigo=codigo, precio=precio, importe=importe)


def extraer(lectura: Lectura, tipo: str | None = None) -> Documento:
    texto = lectura.texto
    tipo = tipo or detectar_tipo(texto)
    doc = Documento(tipo=tipo, metodo=lectura.metodo, confianza=lectura.confianza)
    sup = texto.upper()

    # RUC: el del proveedor en la OC va rotulado; en factura y guía el emisor va arriba.
    rucs = RE_RUC.findall(texto)
    for l in lectura.lineas:
        if "PROVEEDOR" in l.texto.upper() and (m := RE_RUC.search(l.texto)):
            doc.ruc_proveedor = m.group()
    if rucs:
        doc.ruc_emisor = rucs[0]
    if tipo == "orden_compra" and not doc.ruc_proveedor:
        doc.ruc_proveedor = next((r for r in rucs if r != doc.ruc_emisor), "")

    # Razón social: la primera línea del documento, que suele ser el emisor.
    for l in lectura.lineas[:4]:
        t = l.celdas[0].texto
        if not RE_RUC.search(t) and "DOCUMENTO DE PRUEBA" not in t.upper() and "SIN VALOR" not in t.upper():
            doc.razon_social = t
            break

    # Número del documento y referencias cruzadas.
    if tipo == "factura":
        if m := RE_FACTURA.search(sup):
            doc.numero = f"{m.group(1)}-{int(m.group(2)):08d}"
    elif tipo == "guia":
        if m := RE_GUIA.search(sup):
            doc.numero = f"{m.group(1)}-{int(m.group(2)):08d}"
    if m := RE_OC.search(sup):
        oc = re.sub(r"\s", "-", m.group().upper())
        if tipo == "orden_compra":
            doc.numero = oc
        else:
            doc.ref_oc = oc
    if tipo == "factura":
        for l in lectura.lineas:
            if "GU" in l.texto.upper() and "REMISI" in l.texto.upper() and (m := RE_GUIA.search(l.texto.upper().split("REMISI")[-1])):
                doc.ref_guia = f"{m.group(1)}-{int(m.group(2)):08d}"
    if m := RE_FECHA.search(texto):
        doc.fecha = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    # Ítems: filas que empiezan con una cantidad, después del encabezado de la tabla.
    con_precio = tipo != "guia"
    en_tabla = False
    for l in lectura.lineas:
        u = l.texto.upper()
        if not en_tabla:
            en_tabla = ("CANT" in u and ("DESCRIP" in u or "UNID" in u))
            continue
        if any(k in u for k in ("GRAVADA", "IGV", "IMPORTE TOTAL", "RECIBIDO", "SUBTOTAL")):
            break
        if it := _item(l, con_precio):
            doc.items.append(it)

    # Totales.
    for l in lectura.lineas:
        u = l.texto.upper()
        if "GRAVADA" in u or "SUBTOTAL" in u or "VALOR VENTA" in u:
            doc.subtotal = _ultimo_numero(l)
        elif "IGV" in u and "TOTAL" not in u:
            doc.igv = _ultimo_numero(l)
        elif "TOTAL" in u:
            doc.total = _ultimo_numero(l)
    return doc
