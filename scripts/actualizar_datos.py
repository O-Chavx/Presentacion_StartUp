"""Descarga los datos públicos que usa Conforme y los guarda en parquet.

1. Padrón reducido de RUC de la SUNAT (unos 395 MB comprimidos, actualizado a diario).
   Solo se guardan las personas jurídicas (RUC que empieza con 20), con su estado y
   condición de domicilio. Las personas naturales (RUC 10) se dejan fuera a propósito.
2. Proveedores sancionados por el Tribunal de Contrataciones del Estado (OSCE/OECE),
   inhabilitaciones y multas, publicados en datos abiertos.

Uso:
    python scripts/actualizar_datos.py            # descarga todo
    python scripts/actualizar_datos.py --solo-osce
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "data" / "publicos"

URL_PADRON = "http://www2.sunat.gob.pe/padron_reducido_ruc.zip"
URL_OSCE = "https://osce-gob-pe.atlassian.net/wiki/download/attachments/106889269/{archivo}?api=v2"
ARCHIVOS_OSCE = {"inhabilitados": "sancionados.csv", "multas": "sancionados_multa.csv"}


def descargar(url: str, ruta: Path) -> None:
    print(f"Descargando {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "conforme/0.1"})
    with urllib.request.urlopen(req, timeout=600) as r, open(ruta, "wb") as f:
        while bloque := r.read(1 << 20):
            f.write(bloque)


def padron() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "padron.zip"
        txt_path = Path(tmp) / "empresas.txt"
        descargar(URL_PADRON, zip_path)
        n = 0
        with zipfile.ZipFile(zip_path) as z, open(txt_path, "w", encoding="utf-8") as out:
            nombre = z.namelist()[0]
            with z.open(nombre) as f:
                lector = io.TextIOWrapper(f, encoding="latin-1", newline="")
                next(lector)  # encabezado
                for linea in lector:
                    if not linea.startswith("20"):
                        continue
                    campos = linea.split("|")
                    if len(campos) < 5:
                        continue
                    out.write("|".join(c.strip() for c in campos[:5]) + "\n")
                    n += 1
        print(f"Padrón: {n:,} personas jurídicas")
        duckdb.sql(f"""
            COPY (
              SELECT * FROM read_csv('{txt_path}', delim='|', header=false, quote='', all_varchar=true,
                                     names=['ruc','razon_social','estado','condicion','ubigeo'])
            ) TO '{DESTINO / "padron_sunat.parquet"}' (FORMAT parquet, COMPRESSION zstd)
        """)


def osce() -> None:
    for clave, archivo in ARCHIVOS_OSCE.items():
        with tempfile.TemporaryDirectory() as tmp:
            crudo = Path(tmp) / archivo
            descargar(URL_OSCE.format(archivo=archivo), crudo)
            utf8 = Path(tmp) / f"{clave}.csv"
            utf8.write_text(crudo.read_bytes().decode("latin-1").replace("\r\n", "\n"), encoding="utf-8")
            duckdb.sql(f"""
                COPY (
                  SELECT * FROM read_csv('{utf8}', delim='|', header=true, quote='', all_varchar=true)
                ) TO '{DESTINO / f"osce_{clave}.parquet"}' (FORMAT parquet)
            """)
            n = duckdb.sql(f"SELECT count(*) FROM '{DESTINO / f'osce_{clave}.parquet'}'").fetchall()[0][0]
            print(f"OSCE {clave}: {n:,} registros")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo-osce", action="store_true")
    args = p.parse_args()
    DESTINO.mkdir(parents=True, exist_ok=True)
    osce()
    if not args.solo_osce:
        padron()
    return 0


if __name__ == "__main__":
    sys.exit(main())
