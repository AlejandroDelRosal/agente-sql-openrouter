import json
import re

import llm

INSTRUCCIONES = """Eres un agente que escribe SQL para SQLite. Reglas:
- Devuelve UNA sola consulta SELECT, sin explicaciones ni bloques de codigo.
- Usa solo las tablas y columnas del esquema que se te da. Si algo no esta, no lo inventes.
- Los comentarios "--" bajo cada tabla traen valores reales de las columnas de texto. Usa
  exactamente esa forma de escribirlos, o LIKE si el valor que buscas puede ser una variante.
- Muchas columnas tienen NULL, usa filtros "is not null" cuando calcules promedios o medianas.
- Incluye un LIMIT razonable si la consulta puede devolver muchas filas.
"""


def limpiar_sql(texto):
    # los modelos suelen envolver la respuesta en ```sql ... ```
    sin_cercas = re.sub(r"```(?:sql)?", "", texto)
    return sin_cercas.strip().rstrip(";").strip()


def escribir_sql(pregunta, plan, esquema, sql_previo=None, error_previo=None):
    partes = [
        f"Pregunta: {pregunta}",
        f"Plan: {json.dumps(plan, ensure_ascii=False)}",
        f"Esquema disponible:\n{esquema}",
    ]
    # el reintento usa la misma funcion, solo cambia que llega el error del intento anterior
    if error_previo:
        partes.append(
            f"Tu intento anterior fue:\n{sql_previo}\n\n"
            f"y fallo asi: {error_previo}\n\nCorrigelo y devuelve la consulta completa."
        )
    mensajes = [
        {"role": "system", "content": INSTRUCCIONES},
        {"role": "user", "content": "\n\n".join(partes)},
    ]
    return limpiar_sql(llm.chat("MODELO_SQL", mensajes))
