import argparse
import os
import re

import db
import llm
import retriever
import validacion
from agentes import analyst, planner, sql_agent

TABLAS_PARA_EL_SQL_AGENT = 2
INTENTOS = 3


def romper(sql):
    # solo para el demo: mete una columna inexistente para disparar el paso de reflection
    return re.sub(r"\bfrom\b", ", columna_que_no_existe from", sql, count=1, flags=re.IGNORECASE)


def correr(pregunta, romper_primer_intento=False):
    plan = planner.planear(pregunta)
    print(f"[1/6] PLANNER      {plan['intencion']}")
    print(f"                   conceptos: {plan['conceptos']}")

    puntajes = retriever.buscar_tablas(plan["conceptos"])
    elegidas = [nombre for _, nombre in puntajes[:TABLAS_PARA_EL_SQL_AGENT]]
    print("[2/6] BUSQUEDA     " + " | ".join(f"{n} {p}" for p, n in puntajes))
    print(f"                   se le pasan al SQL Agent: {elegidas}")
    esquema = retriever.esquema_de(elegidas)

    sql = None
    motivo = None
    columnas, filas = None, None
    for intento in range(1, INTENTOS + 1):
        sql = sql_agent.escribir_sql(pregunta, plan, esquema, sql, motivo)
        if romper_primer_intento and intento == 1:
            sql = romper(sql)
        etiqueta = "SQL AGENT" if intento == 1 else f"SQL AGENT (intento {intento}/{INTENTOS})"
        print(f"[3/6] {etiqueta}    {' '.join(sql.split())}")

        columnas, filas, error = db.ejecutar_select(sql)
        if filas is None:
            resumen = "la consulta no corrio"
        else:
            resumen = f"{len(filas)} fila" + ("s" if len(filas) != 1 else "")
        print(f"[4/6] EJECUCION    {resumen}")

        ok, motivo = validacion.revisar(filas, error)
        print(f"[5/6] VALIDACION   {'ok' if ok else 'falla: ' + motivo}")
        if ok:
            break
        if intento < INTENTOS:
            print("                   reflection: vuelve al SQL Agent con el error")

    respuesta = analyst.analizar(pregunta, sql, columnas, filas, motivo)
    print(f"[6/6] ANALYST      {respuesta}")
    print(
        f"\n{llm.uso['llamadas']} llamadas a OpenRouter | "
        f"{llm.uso['prompt_tokens']} tokens de entrada | "
        f"{llm.uso['completion_tokens']} tokens de salida"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente que responde preguntas sobre exoplanetas")
    parser.add_argument("pregunta")
    parser.add_argument("--debug", action="store_true", help="imprime los prompts que se envian")
    parser.add_argument(
        "--romper-sql",
        action="store_true",
        help="daña el primer SQL a proposito para ver el loop de reflection",
    )
    argumentos = parser.parse_args()
    llm.debug = argumentos.debug
    if not os.path.exists(db.ARCHIVO):
        db.crear_db()
    correr(argumentos.pregunta, argumentos.romper_sql)
