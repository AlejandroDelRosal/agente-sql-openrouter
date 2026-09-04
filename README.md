# Agente SQL sobre exoplanetas, con OpenRouter

Ejemplo de patrones agénticos: en vez de una sola llamada a un modelo, la pregunta pasa por seis
pasos y cada uno vive en su propio archivo.

```
pregunta
  -> Planner            (agentes/planner.py)   arma un plan y saca los conceptos a buscar
  -> búsqueda semántica (retriever.py)         embeddings + coseno para elegir tablas
  -> SQL Agent          (agentes/sql_agent.py) escribe la consulta viendo solo esas tablas
  -> ejecución          (db.py)                SQLite en modo solo lectura, con guardarraíles
  -> validación         (validacion.py)        ¿sirve el resultado? si no, vuelve al SQL Agent
  -> Analyst            (agentes/analyst.py)   redacta la respuesta con las filas obtenidas
respuesta
```

Los tres agentes y los embeddings salen de OpenRouter con una sola llave. Cada rol usa un modelo
distinto, definido por variable de entorno.

## Los datos son reales

La base se construye con tres consultas SQL al servicio TAP del
[NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html), que es
público y acepta ADQL sobre HTTP. No hay CSV en el repo: lo que se versiona es la consulta, no la
extracción. Las consultas están en `CONSULTAS_TAP` dentro de `db.py`.

| tabla | qué tiene | filas |
|---|---|---|
| `exoplanetas` | un planeta confirmado por fila, de `pscomppars` | 6360 |
| `estrellas` | la estrella anfitriona, con `select distinct` sobre la misma tabla | 4769 |
| `mediciones` | un valor publicado por fila desde 2020, de `ps`, así que hay varias por planeta | 7317 |

Los conteos son del 4 de septiembre de 2026 y van a crecer, la NASA publica planetas cada semana.

Dos cosas que la base enseña sola:
- El `select distinct` devuelve 4995 filas pero solo 4769 estrellas únicas: hay estrellas con
  valores estelares inconsistentes entre sus propios planetas. El seed usa `insert or ignore` y
  reporta cuántas descartó.
- Hay muchos `NULL`. `tipo_espectral` viene vacío en la mayoría, y `masa_tierras` falta en los
  planetas de tránsito sin seguimiento por velocidad radial. Por eso la validación revisa si todo
  vino en `NULL` y el Analyst tiene instrucciones de advertir cuando la muestra es incompleta.

## Cómo correrlo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y pega tu llave de OpenRouter en OPENROUTER_API_KEY
python db.py              # baja los datos y arma exoplanetas.db, una sola vez
python main.py "¿Cuántos exoplanetas se descubrieron por tránsito cada año desde 2015?"
```

Salida:

```
[1/6] PLANNER      El usuario quiere saber el número de exoplanetas descubiertos por el método de
                   tránsito por año, a partir de 2015.
                   conceptos: ['Método de detección de exoplanetas.', 'Año de descubrimiento de
                   exoplanetas.', 'Conteo de exoplanetas.']
[2/6] BUSQUEDA     exoplanetas 0.608 | mediciones 0.512 | estrellas 0.51
                   se le pasan al SQL Agent: ['exoplanetas', 'mediciones']
[3/6] SQL AGENT    SELECT anio_descubrimiento, COUNT(*) as cantidad FROM exoplanetas WHERE
                   metodo_descubrimiento = 'Transit' AND anio_descubrimiento >= 2015 GROUP BY 1
[4/6] EJECUCION    12 filas
[5/6] VALIDACION   ok
[6/6] ANALYST      Desde 2015 se han descubierto 3.538 exoplanetas utilizando el método de
                   tránsito. El año con el mayor número de descubrimientos fue 2016, con 1.432 ...

4 llamadas a OpenRouter | 1232 tokens de entrada | 318 tokens de salida
```

Dos flags:

- `--debug` imprime los prompts completos que se enviaron a cada modelo.
- `--romper-sql` daña el primer SQL a propósito para ver el loop de reflection funcionando.

```bash
python main.py --romper-sql "¿Radio promedio de los planetas descubiertos por TESS?"
```

Y los checks, que corren sin llave y sin internet:

```bash
python test_pipeline.py
```

## Por qué cada paso existe

**Planner.** Sin él habría que decidir a mano qué buscar. Su salida no es decorativa: los
`conceptos` que devuelve son lo que se manda a embeddings, así que cambian qué tablas ve el SQL
Agent. Usa structured outputs de OpenRouter (`response_format: json_schema`) para que la respuesta
sea JSON parseable, con reintento en modo JSON libre porque no todos los modelos respetan el schema
estricto.

**Búsqueda semántica.** Con tres tablas cabrían todas en el prompt. Con trescientas no, y ahí está
el punto: el retriever compara los conceptos del plan contra las descripciones de las tablas y
pasa solo las dos mejores. El coseno está escrito a mano en `retriever.py`, son cuatro líneas y se
ve exactamente qué se está midiendo. Los puntajes se imprimen, así que la selección es auditable
en vez de ser un prompt gigante que uno espera que funcione.

**SQL Agent.** Es el paso que más se equivoca, y por eso usa el modelo más fuerte. Recibe la
pregunta, el plan y el DDL de las tablas ganadoras, más los valores reales de sus columnas de
texto. Eso último no estaba en la primera versión y el demo se cayó en la primera pregunta sobre
telescopios: el agente escribió `instalacion_descubrimiento = 'TESS'` y la base guarda
`'Transiting Exoplanet Survey Satellite (TESS)'`. Cero filas, y la reflection no puede adivinar una
cadena que nunca vio. `db.valores_de_ejemplo` resuelve eso: para cada columna de texto con menos de
500 valores distintos, agrega los ocho más frecuentes como comentario debajo del DDL.

```
create table exoplanetas ( ... )
-- metodo_descubrimiento (los mas frecuentes de 11): 'Transit', 'Radial Velocity', 'Microlensing', ...
-- instalacion_descubrimiento (los mas frecuentes de 73): 'Kepler', 'Transiting Exoplanet Survey Satellite (TESS)', ...
```

El umbral de 500 es lo que deja fuera a `nombre` y `estrella`, que son casi identificadores únicos
y no aportarían nada. Con el comentario puesto, la misma pregunta sale bien al primer intento.

**Ejecución.** El agente no es confiable, así que la base se defiende: conexión `mode=ro`, solo se
aceptan sentencias que empiezan con `select` o `with`, se rechaza cualquier `;` intermedio para
cortar sentencias encadenadas, y se fuerza un `limit 200` si la consulta no trae uno. Los errores
de SQLite se devuelven en vez de lanzarse, porque son el insumo del paso siguiente.

**Validación / reflection.** Es el patrón central del ejemplo. Los checks son deterministas y sin
LLM: hubo error de SQLite, vinieron cero filas, o todo vino en `NULL`. Si algo falla, el motivo
vuelve al SQL Agent como parte del prompt y se reintenta, hasta tres intentos. El reintento usa la
misma función `escribir_sql`, solo cambia que ahora recibe el error anterior. Un juez LLM aquí
sería más lento, más caro y taparía que estos tres checks atrapan la gran mayoría de los fallos
reales.

**Analyst.** Redacta con las filas ya obtenidas y no toca la base. Separarlo del SQL Agent importa
porque son dos habilidades distintas: escribir SQL correcto y explicar un número sin inventar
otros. Si la validación falló después de los tres intentos, se le dice, y contesta que no se pudo
responder en vez de improvisar una cifra.

## Guion de la exposición, 30 minutos

| min | tema |
|---|---|
| 0-3 | El problema y los datos: 6360 exoplanetas bajados con SQL del archivo de la NASA |
| 3-6 | Por qué no una sola llamada al modelo: el esquema no cabe y el SQL malo pasa silencioso |
| 6-10 | Pasos 1 y 2: Planner y búsqueda semántica, con los puntajes de coseno en pantalla |
| 10-16 | Pasos 3 y 4: SQL Agent, los valores de ejemplo, y los guardarraíles de ejecución |
| 16-22 | Paso 5: reflection en vivo con `--romper-sql` |
| 22-26 | Paso 6: Analyst, y por qué el que redacta no toca la base |
| 26-30 | OpenRouter: cambiar el modelo de un rol con una variable de entorno, y el costo por corrida |

## Fuera de alcance, a propósito

- Memoria entre preguntas. Cada corrida arranca de cero.
- Cache de los embeddings del catálogo. Con tres tablas es una llamada barata; vale la pena cuando
  el catálogo pase de unas cincuenta tablas.
- Un juez LLM en la validación. Los checks deterministas cubren los fallos que de verdad ocurren.
- pytest, CI, Docker. `test_pipeline.py` son asserts que corren con `python test_pipeline.py`.
- Que el agente consulte el TAP de la NASA en vivo. Apunta a SQLite local porque ese es el caso
  realista, una base interna de la empresa.

## Publicar

```bash
git init -b main
git add .
git commit -m "Pipeline agentico Planner, SQL Agent y Analyst sobre OpenRouter"
gh repo create agente-sql-openrouter --public --source=. --push
```

`git status` no debe listar `.env` antes de hacer push: la llave se queda en tu máquina.
