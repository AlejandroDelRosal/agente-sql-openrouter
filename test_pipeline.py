import sqlite3
import tempfile

import db
import llm
import main

try:
    import grafo
except ImportError:
    grafo = None
import retriever
import validacion
from agentes import sql_agent

# bolsa de palabras minima, para probar el ranking del retriever sin llamar a OpenRouter
PALABRAS = ["planeta", "estrella", "publicacion", "radio", "espectral"]


def embeddings_falsos(textos):
    return [[float(texto.lower().count(palabra)) for palabra in PALABRAS] for texto in textos]


def base_de_prueba():
    ruta = tempfile.mktemp(suffix=".db")
    conexion = sqlite3.connect(ruta)
    for sentencia in db.DDL.values():
        conexion.execute(sentencia)
    conexion.executemany(
        "insert into exoplanetas values (?,?,?,?,?,?,?,?,?)",
        [
            ("Prueba b", "Prueba", 2020, "Transit", "1.5e+00", "3.2e+00", "10.0", "12.0", "TESS"),
            ("Prueba c", "Prueba", 2021, "Transit", "2.5e+00", None, "20.0", "12.0", "TESS"),
            ("Prueba d", "Prueba", 2022, "Radial Velocity", None, "9.0", "30.0", "12.0", "HARPS"),
        ],
    )
    conexion.commit()
    conexion.close()
    return ruta


def test_limite():
    assert db.agregar_limite("select 1").endswith("limit 200")
    assert db.agregar_limite("select 1 limit 5") == "select 1 limit 5"


def test_guardarrailes(ruta):
    for sql in [
        "delete from exoplanetas",
        "update exoplanetas set nombre = 'x'",
        "drop table estrellas",
        "select 1; drop table estrellas",
        "select 'la respuesta es 42' as mensaje",
    ]:
        _, _, error = db.ejecutar_select(sql, ruta)
        assert error.startswith("rechazado"), sql

    # segunda capa: aunque el prefijo pasara el filtro, la conexion es de solo lectura
    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        conexion.execute("delete from exoplanetas")
        raise AssertionError("la conexion de solo lectura permitio escribir")
    except sqlite3.OperationalError:
        pass
    conexion.close()


def test_consulta_valida(ruta):
    columnas, filas, error = db.ejecutar_select("select count(*) as n from exoplanetas", ruta)
    assert error is None
    assert columnas == ["n"]
    assert filas == [(3,)]

    # las columnas declaradas real castean el texto en notacion cientifica que devuelve el TAP
    _, filas, _ = db.ejecutar_select("select avg(radio_tierras) from exoplanetas", ruta)
    assert abs(filas[0][0] - 2.0) < 1e-9


def test_valores_de_ejemplo(ruta):
    db.MAX_DISTINTOS = 2
    texto = db.valores_de_ejemplo("exoplanetas", ruta)
    db.MAX_DISTINTOS = 500
    # se muestran las columnas de texto de baja cardinalidad; nombre tiene 3 valores y queda fuera
    assert "'Transit'" in texto
    assert "'TESS'" in texto
    assert "-- nombre" not in texto


def test_coseno():
    assert retriever.coseno([1, 0], [1, 0]) == 1
    assert retriever.coseno([1, 0], [0, 1]) == 0
    assert retriever.coseno([1, 0], [0, 0]) == 0


def test_busqueda_semantica():
    llm.embeddings = embeddings_falsos
    puntajes = retriever.buscar_tablas(["tipo espectral de las estrellas anfitrionas"])
    assert puntajes[0][1] == "estrellas", puntajes
    puntajes = retriever.buscar_tablas(["cuantas publicaciones tiene cada planeta"])
    assert puntajes[0][1] == "mediciones", puntajes


def test_validacion():
    assert validacion.revisar(None, "no such column: x")[0] is False
    assert validacion.revisar([], None)[0] is False
    assert validacion.revisar([(None,), (None,)], None)[0] is False
    assert validacion.revisar([(3,)], None) == (True, "ok")


def test_limpiar_sql():
    assert sql_agent.limpiar_sql("```sql\nselect 1;\n```") == "select 1"


def test_parece_sql():
    assert sql_agent.parece_sql("select 1 from t")
    assert sql_agent.parece_sql("with x as (select 1) select * from x")
    # una negativa en prosa no es un error de SQL que convenga reintentar
    assert not sql_agent.parece_sql("Lo siento, no puedo responder eso con estas tablas.")


def test_reflection_se_dispara(ruta):
    roto = main.romper("select nombre from exoplanetas")
    _, _, error = db.ejecutar_select(roto, ruta)
    assert "columna_que_no_existe" in error
    assert validacion.revisar(None, error)[0] is False


def test_rutas_del_grafo():
    base = {"puntajes": [(0.6, "a"), (0.5, "b"), (0.4, "c")], "elegidas": ["a", "b"], "intento": 1}

    # con SQL valido siempre se va a ejecutar, sin importar el resto del estado
    assert grafo.ruta_despues_de_escribir({**base, "sql": "select 1 from t"}) == "ejecutar"
    # un rechazo en prosa amplia el esquema mientras queden tablas, y despues se rinde
    assert grafo.ruta_despues_de_escribir({**base, "sql": "no puedo"}) == "ampliar_esquema"
    sin_tablas = {**base, "elegidas": ["a", "b", "c"], "sql": "no puedo", "motivo": "rechazo"}
    assert grafo.ruta_despues_de_escribir(sin_tablas) == "analizar"

    assert grafo.ruta_despues_de_validar({**base, "ok": True, "motivo": "ok"}) == "analizar"
    fallo = {**base, "ok": False, "motivo": "no such column: x"}
    assert grafo.ruta_despues_de_validar(fallo) == "escribir_sql"
    falta_tabla = {**base, "ok": False, "motivo": "no such table: mediciones"}
    assert grafo.ruta_despues_de_validar(falta_tabla) == "ampliar_esquema"
    # agotados los intentos se pasa al Analyst aunque siga fallando
    agotado = {**base, "ok": False, "motivo": "no such column: x", "intento": 3}
    assert grafo.ruta_despues_de_validar(agotado) == "analizar"


if __name__ == "__main__":
    ruta = base_de_prueba()
    test_limite()
    test_guardarrailes(ruta)
    test_consulta_valida(ruta)
    test_valores_de_ejemplo(ruta)
    test_coseno()
    test_busqueda_semantica()
    test_validacion()
    test_limpiar_sql()
    test_parece_sql()
    if grafo:
        test_rutas_del_grafo()
    else:
        print("langgraph no esta instalado, se salta el test del grafo")
    test_reflection_se_dispara(ruta)
    print("todo bien")
