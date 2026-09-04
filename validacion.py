def revisar(filas, error):
    if error:
        return False, error
    if not filas:
        return False, "la consulta no devolvio filas, revisa los filtros y los rangos"
    if all(celda is None for fila in filas for celda in fila):
        return False, (
            "todas las celdas vienen en NULL: o las columnas elegidas estan vacias, o los "
            "filtros de texto no coinciden con ningun valor real"
        )
    return True, "ok"
