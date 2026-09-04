import math

import db
import llm

# la descripcion es lo unico que se manda a embeddings; el ddl solo viaja al SQL Agent
# si la tabla gana la busqueda
CATALOGO = [
    {
        "nombre": "exoplanetas",
        "descripcion": (
            "planetas confirmados fuera del sistema solar, uno por fila, con su radio en radios "
            "terrestres, masa en masas terrestres, periodo orbital en dias, distancia en parsecs, "
            "el anio y el metodo con el que fueron descubiertos (transito, velocidad radial, "
            "microlente, imagen directa) y el observatorio que los detecto"
        ),
    },
    {
        "nombre": "estrellas",
        "descripcion": (
            "estrellas anfitrionas de los planetas, con tipo espectral, masa y radio en unidades "
            "solares, temperatura efectiva en kelvin y distancia en parsecs"
        ),
    },
    {
        "nombre": "mediciones",
        "descripcion": (
            "valores publicados por distintos papers para el mismo planeta desde 2020, con la "
            "fecha de publicacion y el observatorio, sirve para comparar mediciones repetidas, "
            "ver dispersion entre fuentes o contar cuantas publicaciones tiene un planeta"
        ),
    },
]


def coseno(a, b):
    producto = sum(x * y for x, y in zip(a, b))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0 or norma_b == 0:
        return 0.0
    return producto / (norma_a * norma_b)


def buscar_tablas(conceptos):
    # una sola llamada con todo junto: descripciones primero, conceptos del plan despues
    vectores = llm.embeddings([tabla["descripcion"] for tabla in CATALOGO] + conceptos)
    vectores_tablas = vectores[: len(CATALOGO)]
    vectores_conceptos = vectores[len(CATALOGO) :]
    puntajes = []
    for tabla, vector in zip(CATALOGO, vectores_tablas):
        # el puntaje de una tabla es su mejor coincidencia contra cualquiera de los conceptos
        mejor = max(coseno(vector, concepto) for concepto in vectores_conceptos)
        puntajes.append((round(mejor, 3), tabla["nombre"]))
    puntajes.sort(reverse=True)
    return puntajes


def esquema_de(nombres):
    bloques = [db.DDL[n].strip() + "\n" + db.valores_de_ejemplo(n) for n in nombres]
    return "\n\n".join(bloques)
