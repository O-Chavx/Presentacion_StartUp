"""Pruebas del flujo completo con los 3 casos de ejemplo (PDF, sin OCR)."""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.cruce import ROJO, VERDE, cruzar  # noqa: E402
from core.extraccion import extraer, numero  # noqa: E402
from core.lectura import leer  # noqa: E402
from core.proveedores import consultar, datos_disponibles, ruc_valido  # noqa: E402

EJ = RAIZ / "data" / "ejemplos"


def revisar(caso: str, con_ficha: bool = True):
    d = EJ / caso
    f = extraer(leer(d / "factura.pdf"))
    oc = extraer(leer(d / "orden_compra.pdf"))
    g = extraer(leer(d / "guia_remision.pdf"))
    return f, oc, g, cruzar(f, oc, g, consultar(f.ruc_emisor) if con_ficha else None)


def test_ruc_valido():
    assert ruc_valido("20123531389")
    assert ruc_valido("20000000001")
    assert not ruc_valido("20123531388")
    assert not ruc_valido("123")


@pytest.mark.parametrize("texto, valor", [("2,376.00", 2376.0), ("198.00", 198.0), ("12,50", 12.5), ("1,250", 1250.0), ("BAL", None)])
def test_numero(texto, valor):
    assert numero(texto) == valor


def test_tipos_detectados():
    f, oc, g, _ = revisar("caso_1_cuadra", con_ficha=False)
    assert (f.tipo, oc.tipo, g.tipo) == ("factura", "orden_compra", "guia")
    assert f.numero == "F001-00012877" and f.ref_oc == oc.numero and f.ref_guia == g.numero
    assert oc.ruc_proveedor == f.ruc_emisor == g.ruc_emisor
    assert len(f.items) == len(oc.items) == len(g.items) == 3


def test_caso_que_cuadra():
    *_, r = revisar("caso_1_cuadra", con_ficha=False)
    assert r.nivel == VERDE and r.a_retener == 0


def test_caso_descuadre():
    *_, r = revisar("caso_2_descuadre", con_ficha=False)
    assert r.nivel == ROJO
    temas = {a.tema for a in r.alertas}
    assert {"Precio", "Guía"} <= temas
    # 10 baldes a 185 + 6 imprimantes a 72, con IGV
    assert r.total_correcto == pytest.approx((10 * 185 + 6 * 72) * 1.18, abs=0.01)
    assert r.a_retener == pytest.approx(620.68, abs=0.01)


@pytest.mark.skipif(not datos_disponibles()["osce"], reason="faltan los datos del OSCE")
def test_caso_riesgo_osce():
    *_, r = revisar("caso_3_riesgo")
    assert r.nivel == ROJO
    assert any(a.tema == "OSCE" for a in r.alertas)


@pytest.mark.skipif(not datos_disponibles()["sunat"], reason="falta el padrón de la SUNAT")
def test_padron_sunat():
    ficha = consultar("20101571701")
    assert ficha.encontrado and ficha.condicion == "NO HABIDO"
