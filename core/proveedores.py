"""Verificación del proveedor con datos públicos: padrón de la SUNAT y sanciones del OSCE.

Los archivos los baja `scripts/actualizar_datos.py` a `data/publicos/`. Se consultan con
DuckDB directamente sobre el parquet, sin cargarlos en memoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import duckdb

DATOS = Path(__file__).resolve().parents[1] / "data" / "publicos"
PADRON = DATOS / "padron_sunat.parquet"
INHABILITADOS = DATOS / "osce_inhabilitados.parquet"
MULTAS = DATOS / "osce_multas.parquet"


def ruc_valido(ruc: str) -> bool:
    """Dígito verificador del RUC (módulo 11)."""
    if len(ruc) != 11 or not ruc.isdigit() or ruc[:2] not in {"10", "15", "16", "17", "20"}:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    resto = 11 - sum(int(d) * p for d, p in zip(ruc[:10], pesos)) % 11
    return int(ruc[10]) == {10: 0, 11: 1}.get(resto, resto)


@dataclass
class Sancion:
    tipo: str  # inhabilitación o multa
    inicio: str
    fin: str
    resolucion: str
    motivo: str
    vigente: bool
    monto: float | None = None


@dataclass
class FichaProveedor:
    ruc: str
    valido: bool
    encontrado: bool = False
    razon_social: str = ""
    estado: str = ""
    condicion: str = ""
    ubigeo: str = ""
    sanciones: list[Sancion] = field(default_factory=list)
    corte_osce: str = ""

    @property
    def activo_habido(self) -> bool:
        return self.estado == "ACTIVO" and self.condicion == "HABIDO"

    @property
    def sancion_vigente(self) -> Sancion | None:
        return next((s for s in self.sanciones if s.vigente and s.tipo == "inhabilitación"), None)


def _fecha(aaaammdd: str | None) -> str:
    if not aaaammdd or len(aaaammdd) < 8:
        return ""
    return f"{aaaammdd[6:8]}/{aaaammdd[4:6]}/{aaaammdd[:4]}"


@lru_cache(maxsize=1)
def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def datos_disponibles() -> dict[str, bool]:
    return {"sunat": PADRON.exists(), "osce": INHABILITADOS.exists()}


def consultar(ruc: str, hoy: date | None = None) -> FichaProveedor:
    ruc = ruc.strip()
    hoy_s = (hoy or date.today()).strftime("%Y%m%d")
    ficha = FichaProveedor(ruc=ruc, valido=ruc_valido(ruc))
    if not ficha.valido:
        return ficha
    con = _con()
    if PADRON.exists():
        fila = con.execute(f"SELECT razon_social, estado, condicion, ubigeo FROM '{PADRON}' WHERE ruc = ?", [ruc]).fetchall()
        if fila:
            ficha.encontrado = True
            ficha.razon_social, ficha.estado, ficha.condicion, ficha.ubigeo = fila[0]
    if INHABILITADOS.exists():
        for corte, ini, fin, res, motivo in con.execute(
            f"SELECT FECHA_CORTE, FECHA_INICIO, FECHA_FIN, NUMERO_RESOLUCION, DE_MOTIVO_INFRACCION FROM '{INHABILITADOS}' WHERE RUC = ? ORDER BY FECHA_INICIO DESC",
            [ruc],
        ).fetchall():
            ficha.corte_osce = _fecha(corte)
            # Sin fecha de fin = inhabilitación definitiva.
            vigente = (ini or "") <= hoy_s and (not fin or fin >= hoy_s)
            ficha.sanciones.append(Sancion("inhabilitación", _fecha(ini), _fecha(fin) or "definitiva", res, (motivo or "").strip(), vigente))
    if MULTAS.exists():
        for ini, fin, res, motivo, monto in con.execute(
            f"SELECT FECHA_INICIO, FECHA_FIN, NUMERO_RESOLUCION, DE_MOTIVO_INFRACCION, MONTO FROM '{MULTAS}' WHERE RUC = ? ORDER BY FECHA_INICIO DESC",
            [ruc],
        ).fetchall():
            try:
                m = float(monto)
            except (TypeError, ValueError):
                m = None
            ficha.sanciones.append(Sancion("multa", _fecha(ini), _fecha(fin), res, (motivo or "").strip(), False, m))
    return ficha


def consultar_lote(rucs: list[str], hoy: date | None = None) -> list[FichaProveedor]:
    return [consultar(r, hoy) for r in dict.fromkeys(r.strip() for r in rucs if r.strip())]
