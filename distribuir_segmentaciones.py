import os
import re
import unicodedata

from drive_common import get_drive_service, move_file

# Carpeta compartida donde Cursalab va dejando automáticamente los archivos de
# Segmentación de las 4 marcas, todos mezclados en un mismo lugar.
CURSALAB_FOLDER_ID = os.environ.get("GDRIVE_CURSALAB_FOLDER_ID")

# Carpeta "Inputs" de cada malla. Se reutilizan los mismos secrets que ya usa
# cada workflow de reporte (run_report_*.yml) para no duplicar IDs por dos lados.
DESTINOS = {
    "Makro": os.environ.get("GDRIVE_INPUT_FOLDER_ID"),
    "PlazaVea": os.environ.get("GDRIVE_INPUT_FOLDER_ID_PLAZAVEA"),
    "Oslo": os.environ.get("GDRIVE_INPUT_FOLDER_ID_OSLO"),
    "Merkao": os.environ.get("GDRIVE_INPUT_FOLDER_ID_MERKAO"),
}

# Palabras clave (ya normalizadas: minúsculas, sin tildes/espacios/guiones) que
# identifican a cada marca dentro del nombre del archivo. Se revisan en este
# orden; no hay solapamiento entre ellas.
PALABRAS_CLAVE = {
    "Makro": ["makro"],
    "PlazaVea": ["plazavea", "veavivanda", "veaviv", "vivanda"],
    "Oslo": ["oslo"],
    "Merkao": ["merkao"],
}


def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto


def detectar_marca(nombre_archivo):
    nombre_normalizado = normalizar(nombre_archivo)
    for marca, claves in PALABRAS_CLAVE.items():
        if any(clave in nombre_normalizado for clave in claves):
            return marca
    return None


def main():
    if not CURSALAB_FOLDER_ID:
        raise ValueError("La variable de entorno 'GDRIVE_CURSALAB_FOLDER_ID' no está configurada.")

    faltantes = [marca for marca, folder_id in DESTINOS.items() if not folder_id]
    if faltantes:
        raise ValueError(f"Faltan los folder IDs de destino para: {faltantes}")

    service = get_drive_service()

    print("Listando archivos en 'archivos cursalab'...")
    query = f"'{CURSALAB_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])

    # Las subcarpetas (si alguna vez se crea alguna ahí) no son archivos a
    # distribuir, se ignoran.
    archivos = [f for f in files if f.get("mimeType") != "application/vnd.google-apps.folder"]

    if not archivos:
        print("No hay archivos pendientes en 'archivos cursalab'.")
        return

    sin_identificar = []
    for archivo in archivos:
        marca = detectar_marca(archivo["name"])
        if marca is None:
            sin_identificar.append(archivo["name"])
            continue

        destino_id = DESTINOS[marca]
        move_file(service, archivo["id"], CURSALAB_FOLDER_ID, destino_id)
        print(f"Movido: '{archivo['name']}' -> Inputs de {marca}")

    if sin_identificar:
        print(
            "Aviso: no se pudo identificar la marca de estos archivos, se dejaron "
            f"sin mover para revisión manual: {sin_identificar}"
        )

    print("Distribución de segmentaciones completada.")


if __name__ == "__main__":
    main()
