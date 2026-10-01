import os
import re
import unicodedata
from collections import defaultdict

from drive_common import get_drive_service, move_file

FECHA_EN_NOMBRE = re.compile(r"(\d{4}-\d{2}-\d{2})")

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


def clave_de_orden(archivo):
    # Se usa la fecha que trae el propio nombre del archivo (ej. "2026-09-30")
    # para saber cuál es el más reciente entre varios de la misma marca; si el
    # nombre no trae fecha, se cae de respaldo a la fecha de modificación en Drive.
    match = FECHA_EN_NOMBRE.search(archivo["name"])
    fecha_nombre = match.group(1) if match else ""
    return (fecha_nombre, archivo.get("modifiedTime", ""))


def ya_hay_segmentacion_pendiente(service, folder_id):
    # procesar_drive.py identifica la Segmentación de una ronda por el prefijo
    # 'segment' en el nombre (ver file_ids['segmentacion']); si ese archivo
    # sigue ahí es porque el reporte diario todavía no corrió y lo archivó en
    # Historial. Mientras siga pendiente, no se debe mandar otra Segmentación
    # encima: el reporte tomaría cualquiera de las dos y generaría datos mal.
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    return any(f["name"].lower().startswith("segment") for f in results.get("files", []))


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
        fields="files(id, name, mimeType, modifiedTime)",
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

    candidatos_por_marca = defaultdict(list)
    sin_identificar = []
    for archivo in archivos:
        marca = detectar_marca(archivo["name"])
        if marca is None:
            sin_identificar.append(archivo["name"])
            continue
        candidatos_por_marca[marca].append(archivo)

    # Si Cursalab dejó más de un archivo pendiente para la misma marca (por
    # ejemplo, nadie corrió esto en varios días y se acumularon 2 o 3), solo se
    # sube a Inputs el más reciente; los demás se dejan intactos en Cursalab
    # para no mandar varias Segmentaciones a la vez y confundir el reporte.
    for marca, candidatos in candidatos_por_marca.items():
        candidatos.sort(key=clave_de_orden)
        mas_reciente = candidatos[-1]
        anteriores = candidatos[:-1]

        destino_id = DESTINOS[marca]

        if ya_hay_segmentacion_pendiente(service, destino_id):
            print(
                f"Aviso: Inputs de {marca} todavía tiene una Segmentación sin procesar "
                f"(el reporte diario no ha corrido). '{mas_reciente['name']}' se deja "
                "esperando en 'archivos cursalab' hasta que se libere Inputs."
            )
            continue

        move_file(service, mas_reciente["id"], CURSALAB_FOLDER_ID, destino_id)
        print(f"Movido: '{mas_reciente['name']}' -> Inputs de {marca}")

        for viejo in anteriores:
            print(
                f"Aviso: '{viejo['name']}' es una Segmentación de {marca} más antigua "
                "que la que se acaba de mover; se dejó sin mover en 'archivos cursalab'."
            )

    if sin_identificar:
        print(
            "Aviso: no se pudo identificar la marca de estos archivos, se dejaron "
            f"sin mover para revisión manual: {sin_identificar}"
        )

    print("Distribución de segmentaciones completada.")


if __name__ == "__main__":
    main()
