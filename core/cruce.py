"""El cruce de tres vías: factura contra orden de compra y guía de remisión.

Es el control que hace a mano un asistente de logística antes de mandar a pagar:
- ¿lo que se factura es lo que se pidió (OC), al precio pactado?
- ¿lo que se factura es lo que llegó a obra (guía)?
- ¿las cuentas de la factura están bien (importes, IGV, total)?
- ¿el proveedor está activo y habido en la SUNAT, y sin inhabilitación del OSCE?

El resultado es una lista de alertas y el monto que conviene retener hasta aclarar.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .extraccion import Documento, Item
from .proveedores import FichaProveedor

TOL_PRECIO = 0.005  # 0.5 %
TOL_SOLES = 0.05
IGV = 0.18

ROJO, AMBAR, VERDE = "rojo", "ámbar", "verde"


@dataclass
class Alerta:
    nivel: str
    tema: str
    mensaje: str
    monto: float = 0.0  # soles sin IGV en juego


@dataclass
class FilaCruce:
    descripcion: str
    codigo: str
    cant_oc: float | None
    cant_guia: float | None
    cant_factura: float | None
    precio_oc: float | None
    precio_factura: float | None
    importe_factura: float | None
    importe_correcto: float | None
    estado: str


@dataclass
class Resultado:
    alertas: list[Alerta] = field(default_factory=list)
    filas: list[FilaCruce] = field(default_factory=list)
    total_factura: float | None = None
    total_correcto: float | None = None

    @property
    def nivel(self) -> str:
        niveles = {a.nivel for a in self.alertas}
        return ROJO if ROJO in niveles else AMBAR if AMBAR in niveles else VERDE

    @property
    def a_retener(self) -> float:
        """Diferencia con IGV entre lo facturado y lo que corresponde pagar."""
        if self.total_factura is None or self.total_correcto is None:
            return 0.0
        return round(max(self.total_factura - self.total_correcto, 0.0), 2)

    @property
    def veredicto(self) -> str:
        return {
            VERDE: "Todo cuadra: se puede pagar.",
            AMBAR: "Revisar antes de pagar.",
            ROJO: "No pagar todavía: hay observaciones.",
        }[self.nivel]


def _norm(t: str) -> str:
    t = t.upper()
    t = re.sub(r"[^A-Z0-9 ]", " ", t.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U").replace("Ñ", "N"))
    return re.sub(r"\s+", " ", t).strip()


def _emparejar(item: Item, otros: list[Item], usados: set[int]) -> Item | None:
    """Busca el mismo producto por código o, si no hay, por parecido de la descripción."""
    if item.codigo:
        for i, o in enumerate(otros):
            if i not in usados and o.codigo and o.codigo == item.codigo:
                usados.add(i)
                return o
    mejor, idx = 0.0, -1
    for i, o in enumerate(otros):
        if i in usados:
            continue
        r = difflib.SequenceMatcher(None, _norm(item.descripcion), _norm(o.descripcion)).ratio()
        if r > mejor:
            mejor, idx = r, i
    if mejor >= 0.75:
        usados.add(idx)
        return otros[idx]
    return None


def _soles(x: float) -> str:
    return f"S/ {x:,.2f}"


def cruzar(factura: Documento, oc: Documento | None = None, guia: Documento | None = None,
           ficha: FichaProveedor | None = None) -> Resultado:
    res = Resultado()
    A = res.alertas.append

    # 1. Proveedor (SUNAT y OSCE).
    if ficha is not None:
        if not ficha.valido:
            A(Alerta(ROJO, "RUC", f"El RUC {ficha.ruc} no es válido (falla el dígito verificador)."))
        elif not ficha.encontrado:
            A(Alerta(AMBAR, "SUNAT", f"El RUC {ficha.ruc} no aparece en el padrón de personas jurídicas de la SUNAT."))
        else:
            if ficha.estado != "ACTIVO":
                A(Alerta(ROJO, "SUNAT", f"El contribuyente figura como «{ficha.estado}» en la SUNAT."))
            if ficha.condicion == "NO HABIDO":
                A(Alerta(ROJO, "SUNAT", "El proveedor está NO HABIDO: el IGV de esta factura podría no darte crédito fiscal."))
            elif ficha.condicion not in ("HABIDO", ""):
                A(Alerta(AMBAR, "SUNAT", f"Condición de domicilio: «{ficha.condicion}»."))
        if s := ficha.sancion_vigente:
            A(Alerta(ROJO, "OSCE", f"Inhabilitado por el Tribunal de Contrataciones del Estado hasta {s.fin} (resolución {s.resolucion}). No puede contratar con el Estado: ojo si la obra es pública."))
        elif any(s.tipo == "inhabilitación" for s in ficha.sanciones):
            A(Alerta(AMBAR, "OSCE", "Tuvo inhabilitaciones del OSCE en el pasado, ya cumplidas."))
        if any(s.tipo == "multa" for s in ficha.sanciones):
            A(Alerta(AMBAR, "OSCE", "Tiene multas registradas por el Tribunal de Contrataciones del Estado."))

    # 2. Que los tres documentos hablen del mismo proveedor y se citen entre sí.
    for nombre, d in (("orden de compra", oc), ("guía", guia)):
        if d and d.ruc_contraparte and factura.ruc_emisor and d.ruc_contraparte != factura.ruc_emisor:
            A(Alerta(ROJO, "RUC", f"El RUC de la factura ({factura.ruc_emisor}) no coincide con el de la {nombre} ({d.ruc_contraparte})."))
    if oc and oc.numero and factura.ref_oc and oc.numero != factura.ref_oc:
        A(Alerta(AMBAR, "Referencia", f"La factura cita la {factura.ref_oc}, pero se adjuntó la {oc.numero}."))
    if guia and guia.numero and factura.ref_guia and guia.numero != factura.ref_guia:
        A(Alerta(AMBAR, "Referencia", f"La factura cita la guía {factura.ref_guia}, pero se adjuntó la {guia.numero}."))

    # 3. Aritmética de la factura.
    suma = round(sum(i.importe or 0 for i in factura.items), 2)
    for i in factura.items:
        if i.precio is not None and i.importe is not None and abs(i.cantidad * i.precio - i.importe) > TOL_SOLES:
            A(Alerta(ROJO, "Cálculo", f"«{i.descripcion}»: {i.cantidad:g} × {i.precio:,.2f} no da {i.importe:,.2f}."))
    if factura.subtotal is not None and factura.items and abs(suma - factura.subtotal) > TOL_SOLES:
        A(Alerta(ROJO, "Cálculo", f"Los ítems suman {_soles(suma)}, pero la factura dice {_soles(factura.subtotal)} de valor de venta."))
    if factura.subtotal is not None and factura.igv is not None and abs(factura.subtotal * IGV - factura.igv) > TOL_SOLES:
        A(Alerta(ROJO, "Cálculo", f"El IGV debería ser {_soles(factura.subtotal * IGV)}, no {_soles(factura.igv)}."))
    if None not in (factura.subtotal, factura.igv, factura.total) and abs(factura.subtotal + factura.igv - factura.total) > TOL_SOLES:
        A(Alerta(ROJO, "Cálculo", f"Valor de venta + IGV no da el total de {_soles(factura.total)}."))

    # 4. Ítem por ítem contra la OC y la guía.
    usados_oc: set[int] = set()
    usados_guia: set[int] = set()
    correcto = 0.0
    for it in factura.items:
        io = _emparejar(it, oc.items, usados_oc) if oc else None
        ig = _emparejar(it, guia.items, usados_guia) if guia else None
        estado = []
        precio_ok = it.precio
        cant_ok = it.cantidad
        if oc:
            if io is None:
                A(Alerta(ROJO, "OC", f"«{it.descripcion}» se factura pero no está en la orden de compra.", it.importe or 0))
                estado.append("no está en la OC")
                cant_ok = 0
            else:
                if io.precio is not None and it.precio is not None and it.precio > io.precio * (1 + TOL_PRECIO):
                    dif = (it.precio - io.precio) * it.cantidad
                    A(Alerta(ROJO, "Precio", f"«{it.descripcion}»: precio {it.precio:,.2f} y en la OC {io.precio:,.2f} (+{(it.precio / io.precio - 1):.1%}).", dif))
                    estado.append("precio mayor")
                    precio_ok = io.precio
                if it.cantidad > io.cantidad:
                    A(Alerta(AMBAR, "OC", f"«{it.descripcion}»: se facturan {it.cantidad:g} y la OC pidió {io.cantidad:g}."))
                    estado.append("más que la OC")
                    cant_ok = min(cant_ok, io.cantidad)
        if guia:
            if ig is None:
                A(Alerta(ROJO, "Guía", f"«{it.descripcion}» se factura pero no figura en la guía de remisión.", it.importe or 0))
                estado.append("no llegó")
                cant_ok = 0
            elif it.cantidad > ig.cantidad:
                faltan = it.cantidad - ig.cantidad
                A(Alerta(ROJO, "Guía", f"«{it.descripcion}»: se facturan {it.cantidad:g} {it.unidad} y a obra llegaron {ig.cantidad:g}.", faltan * (it.precio or 0)))
                estado.append(f"faltan {faltan:g}")
                cant_ok = min(cant_ok, ig.cantidad)
        imp_ok = round(cant_ok * (precio_ok or 0), 2) if precio_ok is not None else None
        correcto += imp_ok or 0
        res.filas.append(FilaCruce(
            it.descripcion, it.codigo, io.cantidad if io else None, ig.cantidad if ig else None, it.cantidad,
            io.precio if io else None, it.precio, it.importe, imp_ok, ", ".join(estado) or "ok",
        ))
    if oc:
        for i, o in enumerate(oc.items):
            if i not in usados_oc:
                A(Alerta(AMBAR, "OC", f"«{o.descripcion}» está en la OC pero no se facturó (¿entrega parcial?)."))

    if factura.total is not None:
        res.total_factura = factura.total
        res.total_correcto = round(correcto * (1 + IGV), 2) if (oc or guia) else factura.total
        if res.a_retener > TOL_SOLES:
            A(Alerta(ROJO, "Monto", f"Se cobran {_soles(res.a_retener)} de más (con IGV): corresponde pagar {_soles(res.total_correcto)}.", 0))
    return res
