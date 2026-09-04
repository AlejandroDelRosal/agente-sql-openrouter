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

### Preguntas probadas


| pregunta | qué muestra |
|---|---|
| ¿Cuántos planetas tiene TRAPPIST-1? | el camino feliz, una tabla, respuesta verificada en 7 |
| ¿Cuántos exoplanetas se descubrieron por tránsito cada año desde 2015? | agregación por año, y el Analyst citando sin sumar |
| ¿Qué tipo espectral tienen las estrellas de los planetas más cercanos a 10 parsecs? | la búsqueda semántica trae dos tablas y el SQL Agent hace el join |
| ¿Radio promedio de los planetas descubiertos por TESS? | los valores de ejemplo salvando el filtro de texto, 6.04 sobre 933 planetas |
| ¿Qué planetas tienen mayor diferencia entre el radio máximo y mínimo publicado? | `mediciones` gana el ranking, y el Analyst avisa que el resultado es basura |
| ¿Quién ganó el mundial de 2022? | el SQL Agent rechaza, la reflection amplía el esquema, y nadie inventa nada |

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

**Ejecución.** El agente no es confiable, así que la base se defiende. Cuatro reglas en
`db.ejecutar_select`: conexión `mode=ro`, solo sentencias que empiezan con `select` o `with`, se
rechaza cualquier `;` intermedio para cortar sentencias encadenadas, y se rechaza una consulta sin
`from`, porque una consulta que no lee ninguna tabla no está consultando nada. Además se fuerza un
`limit 200` si la consulta no trae uno. Los errores de SQLite se devuelven en vez de lanzarse,
porque son el insumo del paso siguiente.

**Validación / reflection.** Es el patrón central del ejemplo. Los checks son deterministas y sin
LLM: hubo error de SQLite, vinieron cero filas, o todo vino en `NULL`. Si algo falla, el motivo
vuelve al SQL Agent como parte del prompt y se reintenta, hasta tres intentos. El reintento usa la
misma función `escribir_sql`, solo cambia que ahora recibe el error anterior. Un juez LLM aquí
sería más lento, más caro y taparía que estos tres checks atrapan la gran mayoría de los fallos
reales.

Dos detalles del loop que no son obvios:

- Si el error es `no such table`, el reintento no vuelve contra las mismas tablas: agrega la
  siguiente mejor del ranking al esquema. La reflection puede pedir más contexto, no solo corregir
  sintaxis.
- Si el SQL Agent responde en prosa en vez de SQL, eso es un rechazo, no un error, y el loop se
  corta ahí mismo. Por qué importa está abajo.

**Analyst.** Redacta con las filas ya obtenidas y no toca la base. Separarlo del SQL Agent importa
porque son dos habilidades distintas: escribir SQL correcto y explicar un número sin inventar
otros. Si la validación falló después de los tres intentos, se le dice, y contesta que no se pudo
responder en vez de improvisar una cifra. Tiene prohibido calcular: los números que escribe deben
aparecer literalmente en las filas. Si la pregunta pide un total y la consulta devolvió un
desglose, dice el desglose y aclara que el total no se calculó.

## Cuatro cosas que se rompieron al probarlo

**1. El agente no sabía cómo se escriben los valores.** Preguntando por el radio promedio de los
planetas de TESS, escribió `instalacion_descubrimiento = 'TESS'`. La base guarda
`'Transiting Exoplanet Survey Satellite (TESS)'`. Cero filas, y la reflection reintentó a ciegas
tres veces porque no puede adivinar una cadena que nunca vio. Arreglo: mostrarle los valores más
frecuentes de cada columna de texto junto al DDL. La respuesta correcta, 6.04 radios terrestres
sobre 933 planetas, sale al primer intento.

**2. La respuesta inventada se colaba por el canal de los datos.** Preguntando quién ganó el
mundial de 2022, el SQL Agent contestó en prosa que la base no tiene esa información, y de paso que
había ganado Argentina. El guardarraíl rechazó la prosa, la reflection lo acorraló, y en el
tercer intento produjo esto:

```sql
SELECT 'Argentina' AS ganador_mundial_2022 FROM exoplanetas LIMIT 1
```

Consulta válida, una fila, validación en ok, y el Analyst reportó que Argentina ganó el mundial
como si fuera un dato de la base. Ningún guardarraíl SQL puede arreglarlo, porque SQL permite
seleccionar constantes y no hay forma de distinguir un literal de un dato leído. El arreglo es de
diseño: una respuesta en prosa del SQL Agent es un rechazo legítimo, no un error, así que el loop
se corta en el primer intento y nunca se lo acorrala. De paso ahorra dos llamadas al modelo caro.

**3. El Analyst sumaba mal.** Con las 12 filas del conteo por año en la mano, reportó 3.538
planetas en una corrida y 4.161 en otra. El total real es 3537. Sumar doce números es exactamente
lo que un LLM hace mal y lo que una base de datos hace bien, así que ahora tiene prohibido
calcular: solo puede citar números que estén literalmente en las filas. Si hace falta un total, lo
calcula el `SELECT`.

**4. Y una que no es un bug.** Preguntando qué planetas tienen más diferencia entre el radio
máximo y mínimo publicado, el agente escribió la consulta correcta, con `HAVING COUNT(*) > 1` y
todo, y devolvió Kepler-1999 b con una diferencia de 4279 radios terrestres. Ese valor está de
verdad en el archivo de la NASA: sale del catálogo automatizado Q1-Q17 DR24 de candidatos Kepler,
con un ajuste malo. Los dos papers arbitrados del mismo planeta dicen 3.29 y 3.55.

O sea que el pipeline funcionó y la respuesta es basura. `MAX - MIN` es el estadístico menos
robusto que existe, y la tabla `mediciones` mezcla papers arbitrados con catálogos automatizados
superados. No hay arquitectura de agentes que salve de pedir un estadístico no robusto sobre una
fuente heterogénea. Los datos de la NASA no se tocan, se documentan: el Analyst tiene instrucciones
de avisar cuando un valor es físicamente absurdo para su unidad y cuando el estadístico pedido es
sensible a valores extremos, que es justo el trabajo que uno espera de un analista.

## Fuera de alcance

- Memoria entre preguntas. Cada corrida arranca de cero.
- Cache de los embeddings del catálogo. Con tres tablas es una llamada barata; vale la pena cuando
  el catálogo pase de unas cincuenta tablas.
- Un juez LLM en la validación. Los checks deterministas cubren los fallos que de verdad ocurren.
- Que el agente consulte el TAP de la NASA en vivo. Apunta a SQLite local porque ese es el caso
  realista.

## Nota sobre la llave

`.env` está en `.gitignore` y nunca se commitea. Lo único que viaja al repo es `.env.example` con
los nombres de las variables.
