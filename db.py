import csv
import io
import os
import re
import sqlite3

import requests

ARCHIVO = "exoplanetas.db"
TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
LIMITE = 200
MAX_DISTINTOS = 500
EJEMPLOS = 8

DDL = {
    "exoplanetas": """
create table exoplanetas (
    nombre text primary key,
    estrella text,
    anio_descubrimiento integer,
    metodo_descubrimiento text,
    radio_tierras real,
    masa_tierras real,
    periodo_dias real,
    distancia_parsecs real,
    instalacion_descubrimiento text
)""",
    "estrellas": """
create table estrellas (
    nombre text primary key,
    tipo_espectral text,
    masa_solar real,
    temperatura_k real,
    radio_solar real,
    distancia_parsecs real
)""",
    "mediciones": """
create table mediciones (
    planeta text,
    estrella text,
    radio_tierras real,
    masa_tierras real,
    periodo_dias real,
    fecha_publicacion text,
    instalacion text
)""",
}

# el orden de las columnas de cada consulta tiene que coincidir con el orden del DDL de arriba
CONSULTAS_TAP = {
    "exoplanetas": """
select pl_name as nombre, hostname as estrella, disc_year as anio_descubrimiento,
       discoverymethod as metodo_descubrimiento, pl_rade as radio_tierras,
       pl_bmasse as masa_tierras, pl_orbper as periodo_dias, sy_dist as distancia_parsecs,
       disc_facility as instalacion_descubrimiento
from pscomppars""",
    "estrellas": """
select distinct hostname as nombre, st_spectype as tipo_espectral, st_mass as masa_solar,
       st_teff as temperatura_k, st_rad as radio_solar, sy_dist as distancia_parsecs
from pscomppars""",
    "mediciones": """
select pl_name as planeta, hostname as estrella, pl_rade as radio_tierras,
       pl_bmasse as masa_tierras, pl_orbper as periodo_dias, pl_pubdate as fecha_publicacion,
       disc_facility as instalacion
from ps where disc_year >= 2020""",
}


def bajar_del_tap(consulta):
    respuesta = requests.get(TAP, params={"query": consulta, "format": "csv"}, timeout=300)
    if respuesta.status_code != 200:
        raise SystemExit(f"El TAP respondio {respuesta.status_code}: {respuesta.text[:300]}")
    # cuando la consulta esta mal el TAP devuelve un VOTABLE de error, no un csv
    if respuesta.text.lstrip().startswith("<"):
        raise SystemExit(f"El TAP rechazo la consulta: {respuesta.text[:300]}")
    lector = csv.reader(io.StringIO(respuesta.text))
    next(lector)
    # las celdas vacias van como NULL; los numeros llegan como texto y sqlite los castea
    # solo, porque las columnas del DDL estan declaradas real o integer
    return [[celda or None for celda in fila] for fila in lector]


def crear_db(archivo=ARCHIVO):
    if os.path.exists(archivo):
        os.remove(archivo)
    conexion = sqlite3.connect(archivo)
    for sentencia in DDL.values():
        conexion.execute(sentencia)
    for tabla, consulta in CONSULTAS_TAP.items():
        print(f"bajando {tabla} del NASA Exoplanet Archive...")
        filas = bajar_del_tap(consulta)
        marcas = ",".join("?" * len(filas[0]))
        cursor = conexion.executemany(f"insert or ignore into {tabla} values ({marcas})", filas)
        descartadas = len(filas) - cursor.rowcount
        aviso = f", {descartadas} descartadas por clave repetida" if descartadas else ""
        print(f"  {cursor.rowcount} filas en {tabla}{aviso}")
    conexion.commit()
    conexion.close()


def valores_de_ejemplo(tabla, archivo=ARCHIVO):
    # el SQL Agent no puede adivinar como se escriben los valores de texto: TESS aparece como
    # "Transiting Exoplanet Survey Satellite (TESS)". Se le muestran los mas frecuentes de cada
    # columna de texto, salvo las que son practicamente identificadores unicos
    conexion = sqlite3.connect(f"file:{archivo}?mode=ro", uri=True)
    # los nombres se interpolan porque salen del pragma de nuestra propia base, no del usuario
    columnas = [f[1] for f in conexion.execute(f"pragma table_info({tabla})") if f[2].lower() == "text"]
    lineas = []
    for columna in columnas:
        distintos = conexion.execute(f"select count(distinct {columna}) from {tabla}").fetchone()[0]
        if distintos > MAX_DISTINTOS:
            continue
        valores = conexion.execute(
            f"select {columna} from {tabla} where {columna} is not null"
            f" group by 1 order by count(*) desc limit {EJEMPLOS}"
        ).fetchall()
        cola = f" (los mas frecuentes de {distintos})" if distintos > EJEMPLOS else ""
        lineas.append(f"-- {columna}{cola}: " + ", ".join(repr(v[0]) for v in valores))
    conexion.close()
    return "\n".join(lineas)


def agregar_limite(sql):
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return sql + f"\nlimit {LIMITE}"


def ejecutar_select(sql, archivo=ARCHIVO):
    limpio = sql.strip().rstrip(";").strip()
    if ";" in limpio:
        return None, None, "rechazado: solo se permite una sentencia por consulta"
    if not limpio.lower().startswith(("select", "with")):
        return None, None, "rechazado: solo se permiten consultas SELECT"
    try:
        # mode=ro es la garantia real de que el agente no puede escribir en la base
        conexion = sqlite3.connect(f"file:{archivo}?mode=ro", uri=True)
        cursor = conexion.execute(agregar_limite(limpio))
        filas = cursor.fetchall()
        columnas = [descripcion[0] for descripcion in cursor.description]
        conexion.close()
        return columnas, filas, None
    except sqlite3.Error as error:
        # el error se devuelve en vez de lanzarse porque es el insumo del paso de validacion
        return None, None, str(error)


if __name__ == "__main__":
    crear_db()
