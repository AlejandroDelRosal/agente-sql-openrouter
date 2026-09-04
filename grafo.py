import argparse
import os
from typing import TypedDict

from langgraph.graph import END, StateGraph

import db
import llm
import retriever
import validacion
from agentes import analyst, planner, sql_agent
from main import INTENTOS, TABLAS_PARA_EL_SQL_AGENT, romper


class Estado(TypedDict):
    pregunta: str
    plan: dict
    puntajes: list
    elegidas: list
    sql: str
    columnas: list
    filas: list
    motivo: str
    ok: bool
    intento: int
    romper_primer_intento: bool


def planificar(estado):
    plan = planner.planear(estado["pregunta"])
    print(f"[1/6] PLANNER      {plan['intencion']}")
    print(f"                   conceptos: {plan['conceptos']}")
    return {"plan": plan}


def buscar(estado):
    puntajes = retriever.buscar_tablas(estado["plan"]["conceptos"])
    elegidas = [nombre for _, nombre in puntajes[:TABLAS_PARA_EL_SQL_AGENT]]
    print("[2/6] BUSQUEDA     " + " | ".join(f"{n} {p}" for p, n in puntajes))
    print(f"                   se le pasan al SQL Agent: {elegidas}")
    return {"puntajes": puntajes, "elegidas": elegidas}


def escribir_sql(estado):
    intento = estado["intento"] + 1
    esquema = retriever.esquema_de(estado["elegidas"])
    sql = sql_agent.escribir_sql(
        estado["pregunta"], estado["plan"], esquema, estado["sql"], estado["motivo"]
    )
    if estado["romper_primer_intento"] and intento == 1:
        sql = romper(sql)
    etiqueta = "SQL AGENT" if intento == 1 else f"SQL AGENT (intento {intento}/{INTENTOS})"
    if sql_agent.parece_sql(sql):
        print(f"[3/6] {etiqueta}    {' '.join(sql.split())}")
        return {"sql": sql, "intento": intento}
    print(f"[3/6] {etiqueta}    no devolvio SQL, rechaza la pregunta")
    return {
        "sql": sql,
        "intento": intento,
        "motivo": "el SQL Agent no pudo escribir una consulta con las tablas disponibles",
    }


def ampliar_esquema(estado):
    siguiente = estado["puntajes"][len(estado["elegidas"])][1]
    print(f"                   reflection: agrega la tabla {siguiente} al esquema")
    nuevo = {"elegidas": estado["elegidas"] + [siguiente]}
    # una negativa en prosa no se le devuelve como error a corregir, solo se le da mas esquema
    if not sql_agent.parece_sql(estado["sql"]):
        nuevo["sql"] = None
        nuevo["motivo"] = None
    return nuevo


def ejecutar(estado):
    columnas, filas, error = db.ejecutar_select(estado["sql"])
    if filas is None:
        print("[4/6] EJECUCION    la consulta no corrio")
    else:
        print(f"[4/6] EJECUCION    {len(filas)} fila" + ("s" if len(filas) != 1 else ""))
    return {"columnas": columnas, "filas": filas, "motivo": error}


def validar(estado):
    ok, motivo = validacion.revisar(estado["filas"], estado["motivo"])
    print(f"[5/6] VALIDACION   {'ok' if ok else 'falla: ' + motivo}")
    return {"ok": ok, "motivo": motivo}


def analizar(estado):
    # si el SQL Agent rechazo en prosa, su texto no viaja al Analyst: no es una consulta y puede
    # traer la respuesta inventada que el rechazo mismo menciona
    sql = estado["sql"] if sql_agent.parece_sql(estado["sql"] or "") else None
    respuesta = analyst.analizar(
        estado["pregunta"], sql, estado["columnas"], estado["filas"], estado["motivo"]
    )
    print(f"[6/6] ANALYST      {respuesta}")
    return {}


def quedan_tablas(estado):
    return len(estado["elegidas"]) < len(estado["puntajes"])


def ruta_despues_de_escribir(estado):
    if sql_agent.parece_sql(estado["sql"]):
        return "ejecutar"
    # rechazo en prosa: puede ser que le falte una tabla, no que la pregunta sea imposible
    if estado["intento"] < INTENTOS and quedan_tablas(estado):
        return "ampliar_esquema"
    print(f"[5/6] VALIDACION   falla: {estado['motivo']}")
    return "analizar"


def ruta_despues_de_validar(estado):
    if estado["ok"] or estado["intento"] >= INTENTOS:
        return "analizar"
    if "no such table" in estado["motivo"] and quedan_tablas(estado):
        return "ampliar_esquema"
    print("                   reflection: vuelve al SQL Agent con el error")
    return "escribir_sql"


def construir():
    grafo = StateGraph(Estado)
    grafo.add_node("planificar", planificar)
    grafo.add_node("buscar", buscar)
    grafo.add_node("escribir_sql", escribir_sql)
    grafo.add_node("ampliar_esquema", ampliar_esquema)
    grafo.add_node("ejecutar", ejecutar)
    grafo.add_node("validar", validar)
    grafo.add_node("analizar", analizar)

    grafo.set_entry_point("planificar")
    grafo.add_edge("planificar", "buscar")
    grafo.add_edge("buscar", "escribir_sql")
    grafo.add_conditional_edges(
        "escribir_sql",
        ruta_despues_de_escribir,
        {"ejecutar": "ejecutar", "ampliar_esquema": "ampliar_esquema", "analizar": "analizar"},
    )
    grafo.add_edge("ampliar_esquema", "escribir_sql")
    grafo.add_edge("ejecutar", "validar")
    grafo.add_conditional_edges(
        "validar",
        ruta_despues_de_validar,
        {
            "analizar": "analizar",
            "ampliar_esquema": "ampliar_esquema",
            "escribir_sql": "escribir_sql",
        },
    )
    grafo.add_edge("analizar", END)
    return grafo.compile()


ESTADO_INICIAL = {
    "plan": {},
    "puntajes": [],
    "elegidas": [],
    "sql": None,
    "columnas": None,
    "filas": None,
    "motivo": None,
    "ok": False,
    "intento": 0,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="El mismo agente, orquestado con LangGraph")
    parser.add_argument("pregunta", nargs="?")
    parser.add_argument("--debug", action="store_true", help="imprime los prompts que se envian")
    parser.add_argument("--romper-sql", action="store_true", help="daña el primer SQL a proposito")
    parser.add_argument("--diagrama", action="store_true", help="imprime el grafo en mermaid y sale")
    argumentos = parser.parse_args()

    aplicacion = construir()
    if argumentos.diagrama:
        print(aplicacion.get_graph().draw_mermaid())
        raise SystemExit
    if not argumentos.pregunta:
        parser.error("falta la pregunta")

    llm.debug = argumentos.debug
    if not os.path.exists(db.ARCHIVO):
        db.crear_db()
    aplicacion.invoke(
        {
            **ESTADO_INICIAL,
            "pregunta": argumentos.pregunta,
            "romper_primer_intento": argumentos.romper_sql,
        }
    )
    print(
        f"\n{llm.uso['llamadas']} llamadas a OpenRouter | "
        f"{llm.uso['prompt_tokens']} tokens de entrada | "
        f"{llm.uso['completion_tokens']} tokens de salida"
    )
