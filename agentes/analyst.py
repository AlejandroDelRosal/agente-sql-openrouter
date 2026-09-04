import llm

INSTRUCCIONES = """Eres un analista de datos. Recibes una pregunta, la consulta SQL que se corrio y
las filas que devolvio. Redacta la respuesta en 3 a 5 frases:
- No calcules nada. No sumes, no promedies, no restes, no saques porcentajes. Los numeros que
  escribas tienen que aparecer literalmente en las filas. Si la pregunta pide un total y las filas
  vienen desglosadas, di el desglose y aclara que la consulta no calculo el total.
- Empieza por el numero o el hallazgo concreto.
- Explica que significa en el contexto de la pregunta.
- Si son menos de 10 filas, o si hay muchos NULL, advierte que la muestra es chica o incompleta.
- Si un valor es fisicamente absurdo para su unidad, por ejemplo un radio planetario de miles de
  radios terrestres cuando los planetas mas grandes conocidos rondan los 20, dilo: casi siempre es un dato malo de la fuente y no
  un hallazgo. Aclara tambien cuando el estadistico pedido sea sensible a esos valores, como el
  maximo, el minimo o el rango.
No inventes ninguna cifra que no este en las filas. Si las filas vienen vacias o hubo un error,
dilo sin rodeos y no respondas la pregunta.
Si una columna del resultado es una constante escrita dentro del propio SQL en vez de un valor
leido de una tabla, ignorala: no es un dato, es texto que el modelo anterior escribio.
"""


def formatear_filas(columnas, filas, maximo=40):
    if not columnas:
        return "sin resultados"
    lineas = [" | ".join(columnas)]
    for fila in filas[:maximo]:
        lineas.append(" | ".join("NULL" if celda is None else str(celda) for celda in fila))
    if len(filas) > maximo:
        lineas.append(f"... y {len(filas) - maximo} filas mas")
    return "\n".join(lineas)


def analizar(pregunta, sql, columnas, filas, motivo):
    contenido = (
        f"Pregunta: {pregunta}\n\n"
        f"SQL ejecutado:\n{sql or 'ninguno, no se llego a escribir una consulta valida'}\n\n"
        f"Estado de la validacion: {motivo}\n\n"
        f"Filas ({len(filas or [])} en total):\n{formatear_filas(columnas, filas or [])}"
    )
    mensajes = [
        {"role": "system", "content": INSTRUCCIONES},
        {"role": "user", "content": contenido},
    ]
    return llm.chat("MODELO_ANALYST", mensajes)
