# Conforme

Revisamos las facturas de los proveedores de las constructoras pequeñas contra la orden de compra y la guía de remisión, y verificamos el RUC en la SUNAT y el OSCE, antes de pagar.

> README en construcción: la versión completa (problema, solución, demo, modelo de negocio y herramientas del curso) llega en los próximos commits.

## Cómo correrlo

```bash
pip install -r requirements-dev.txt
python scripts/actualizar_datos.py      # baja el padrón de la SUNAT y las sanciones del OSCE
python scripts/generar_ejemplos.py      # genera los 3 casos de ejemplo
streamlit run app/app.py
pytest -q
```
