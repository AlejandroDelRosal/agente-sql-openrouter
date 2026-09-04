import os

import requests

API = "https://openrouter.ai/api/v1"

MODELOS_POR_DEFECTO = {
    "MODELO_PLANNER": "google/gemini-2.5-flash",
    "MODELO_SQL": "anthropic/claude-sonnet-4.5",
    "MODELO_ANALYST": "google/gemini-2.5-flash",
    "MODELO_EMBEDDINGS": "openai/text-embedding-3-small",
}

# lo llena cada llamada y main.py lo imprime al final de la corrida
uso = {"prompt_tokens": 0, "completion_tokens": 0, "llamadas": 0}

debug = False


def cargar_env(ruta=".env"):
    if not os.path.exists(ruta):
        return
    for linea in open(ruta):
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        # setdefault para que una variable ya exportada en la shell gane sobre el .env
        os.environ.setdefault(clave.strip(), valor.strip())


cargar_env()


def modelo(variable):
    return os.environ.get(variable, MODELOS_POR_DEFECTO[variable])


def _cabeceras():
    llave = os.environ.get("OPENROUTER_API_KEY")
    if not llave:
        raise SystemExit("Falta OPENROUTER_API_KEY. Copia .env.example a .env y pega tu llave.")
    return {"Authorization": "Bearer " + llave, "Content-Type": "application/json"}


def _pedir(ruta, cuerpo):
    respuesta = requests.post(API + ruta, headers=_cabeceras(), json=cuerpo, timeout=120)
    if respuesta.status_code != 200:
        raise SystemExit(f"OpenRouter respondio {respuesta.status_code}: {respuesta.text[:400]}")
    datos = respuesta.json()
    # OpenRouter a veces devuelve 200 con un error adentro del cuerpo
    if "error" in datos:
        raise SystemExit(f"OpenRouter devolvio un error: {datos['error']}")
    consumo = datos.get("usage") or {}
    uso["prompt_tokens"] += consumo.get("prompt_tokens", 0)
    uso["completion_tokens"] += consumo.get("completion_tokens", 0)
    uso["llamadas"] += 1
    return datos


def chat(variable_modelo, mensajes, formato=None):
    cuerpo = {"model": modelo(variable_modelo), "messages": mensajes, "temperature": 0}
    if formato:
        cuerpo["response_format"] = formato
    if debug:
        print(f"\n--- prompt enviado a {cuerpo['model']} ---")
        for mensaje in mensajes:
            print(f"[{mensaje['role']}] {mensaje['content']}")
        print("--- fin del prompt ---\n")
    datos = _pedir("/chat/completions", cuerpo)
    return datos["choices"][0]["message"]["content"]


def embeddings(textos):
    cuerpo = {"model": modelo("MODELO_EMBEDDINGS"), "input": textos}
    datos = _pedir("/embeddings", cuerpo)
    return [fila["embedding"] for fila in datos["data"]]
