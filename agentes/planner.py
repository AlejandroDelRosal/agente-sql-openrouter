import json

import llm

ESQUEMA = {
    "type": "object",
    "properties": {
        "intencion": {"type": "string"},
        "conceptos": {"type": "array", "items": {"type": "string"}},
        "pasos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intencion", "conceptos", "pasos"],
    "additionalProperties": False,
}

INSTRUCCIONES = """Eres el planificador de un agente que responde preguntas sobre un catalogo de
exoplanetas guardado en SQLite. No escribes SQL: solo preparas el terreno.

Devuelve:
- intencion: en una frase, que quiere saber la persona.
- conceptos: de 2 a 4 frases cortas que describan los DATOS que se necesitan, no nombres de tablas.
  Estas frases se comparan por similitud semantica contra las descripciones de las tablas, asi que
  escribelas como describirias el contenido de una tabla. Ejemplo: "radio y masa de planetas
  descubiertos por transito", no "tabla exoplanetas".
- pasos: en lenguaje natural, como se calcula la respuesta (que filtrar, que agrupar, que agregar).
"""


def planear(pregunta):
    mensajes = [
        {"role": "system", "content": INSTRUCCIONES},
        {"role": "user", "content": pregunta},
    ]
    formato = {
        "type": "json_schema",
        "json_schema": {"name": "plan", "strict": True, "schema": ESQUEMA},
    }
    texto = llm.chat("MODELO_PLANNER", mensajes, formato)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # no todos los modelos de OpenRouter respetan el schema estricto, se reintenta con json libre
        texto = llm.chat("MODELO_PLANNER", mensajes, {"type": "json_object"})
        return json.loads(texto)
