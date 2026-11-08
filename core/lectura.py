"""Lectura de documentos: de un PDF o una foto a líneas de texto ordenadas.

Hay dos caminos y los dos terminan en lo mismo, una lista de `Linea`, cada una con sus
celdas ordenadas de izquierda a derecha:

- PDF digital (la representación impresa de una factura electrónica): se lee el texto
  con PyMuPDF, sin OCR, que es exacto y rápido.
- Foto o PDF escaneado: se pasa por PaddleOCR (sesión 10 del curso), que devuelve cada
  texto con su caja. Como una foto suele salir un poco girada, se estima la inclinación
  y se corrige antes de armar las filas.
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class Caja:
    texto: str
    x0: float
    y0: float
    x1: float
    y1: float
    confianza: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def alto(self) -> float:
        return self.y1 - self.y0


@dataclass
class Linea:
    celdas: list[Caja] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(c.texto for c in self.celdas)

    @property
    def textos(self) -> list[str]:
        return [c.texto for c in self.celdas]


@dataclass
class Lectura:
    lineas: list[Linea]
    metodo: str  # "pdf" u "ocr"
    confianza: float  # promedio de confianza del OCR (1.0 en PDF digital)

    @property
    def texto(self) -> str:
        return "\n".join(l.texto for l in self.lineas)


def _cajas_pdf(ruta: Path) -> list[Caja]:
    import pymupdf

    cajas: list[Caja] = []
    with pymupdf.open(ruta) as doc:
        pagina = doc[0]
        for bloque in pagina.get_text("dict")["blocks"]:
            for linea in bloque.get("lines", []):
                for span in linea["spans"]:
                    t = span["text"].strip()
                    if t:
                        x0, y0, x1, y1 = span["bbox"]
                        cajas.append(Caja(t, x0, y0, x1, y1))
    return cajas


@lru_cache(maxsize=1)
def _motor_ocr():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang="es",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,  # evita un error de oneDNN en paddle 3.3 con CPU
    )


def _cajas_ocr(ruta: Path) -> list[Caja]:
    entrada = str(ruta)
    if ruta.suffix.lower() == ".pdf":  # PDF escaneado: se rasteriza la primera página
        import pymupdf

        with pymupdf.open(ruta) as doc:
            png = ruta.with_suffix(".ocr.png")
            doc[0].get_pixmap(dpi=200).save(png)
            entrada = str(png)
    r = _motor_ocr().predict(entrada)[0]
    cajas = []
    for t, s, b in zip(r["rec_texts"], r["rec_scores"], r["rec_boxes"]):
        t = t.strip()
        if t and s >= 0.6 and len(t) > 1:
            cajas.append(Caja(t, float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s)))
    return cajas


def _pendiente(cajas: list[Caja]) -> float:
    """Inclinación de la página (dy/dx), estimada con pares de cajas de la misma fila."""
    pendientes = []
    for i, a in enumerate(cajas):
        for b in cajas[i + 1 :]:
            dx = b.cx - a.cx
            if abs(dx) < 150:
                continue
            dy = b.cy - a.cy
            alto = min(a.alto, b.alto)
            if abs(dy) < 0.6 * alto and abs(a.alto - b.alto) < 0.4 * alto:
                pendientes.append(dy / dx)
    return statistics.median(pendientes) if len(pendientes) >= 5 else 0.0


def agrupar_lineas(cajas: list[Caja]) -> list[Linea]:
    if not cajas:
        return []
    m = _pendiente(cajas)
    alto = statistics.median(c.alto for c in cajas)
    tolerancia = 0.5 * alto
    orden = sorted(cajas, key=lambda c: c.cy - m * c.cx)
    lineas: list[tuple[float, Linea]] = []
    for c in orden:
        y = c.cy - m * c.cx
        if lineas and abs(y - lineas[-1][0]) <= tolerancia:
            y_ref, linea = lineas[-1]
            linea.celdas.append(c)
            n = len(linea.celdas)
            lineas[-1] = ((y_ref * (n - 1) + y) / n, linea)
        else:
            lineas.append((y, Linea([c])))
    for _, l in lineas:
        l.celdas.sort(key=lambda c: c.x0)
    return [l for _, l in lineas]


def leer(ruta: str | Path, forzar_ocr: bool = False) -> Lectura:
    ruta = Path(ruta)
    es_imagen = ruta.suffix.lower() in EXT_IMAGEN
    cajas: list[Caja] = []
    metodo = "pdf"
    if not es_imagen and not forzar_ocr:
        cajas = _cajas_pdf(ruta)
    if es_imagen or forzar_ocr or len(cajas) < 5:  # sin texto: es un escaneo
        cajas = _cajas_ocr(ruta)
        metodo = "ocr"
    conf = statistics.mean(c.confianza for c in cajas) if cajas else 0.0
    return Lectura(agrupar_lineas(cajas), metodo, round(conf, 3))
