import json
import os
import re
import unicodedata
from collections import defaultdict

from drive_common import copy_file, download_text, find_file_in_folder, get_drive_service, trash_file, upsert_text_file

FECHA_EN_NOMBRE = re.compile(r"(\d{4}-\d{2}-\d{2})")
ESTADO_NOMBRE = ".distribucion_state.json"

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


def es_archivo_segmentacion(nombre_archivo):
    # El nombre debe decir "Segmentación" Y "Malla" (confirmado con el usuario:
    # así nombra Cursalab todos los archivos reales hoy en día). Exigir ambas
    # palabras evita copiar por error cualquier otro archivo que caiga en esta
    # carpeta compartida, aunque mencione el nombre de una marca.
    nombre_normalizado = normalizar(nombre_archivo)
    return "segmentacion" in nombre_normalizado and "malla" in nombre_normalizado


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


def reemplazar_segmentacion_en_inputs(service, folder_id):
    # El usuario pidió que, si ya hay una Segmentación de ronda anterior sin
    # procesar en Inputs (el reporte diario todavia no corrio), la de hoy la
    # REEMPLACE (no que se acumulen ni que se bloquee la nueva). Se borran
    # todos los archivos que empiecen con 'segment' antes de copiar el nuevo.
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    for f in results.get("files", []):
        if f["name"].lower().startswith("segment"):
            trash_file(service, f["id"])
            print(f"Reemplazado: se eliminó la Segmentación anterior '{f['name']}' de Inputs.")


def cargar_estado(service):
    archivo_estado = find_file_in_folder(service, CURSALAB_FOLDER_ID, ESTADO_NOMBRE)
    if not archivo_estado:
        return {}
    try:
        return json.loads(download_text(service, archivo_estado["id"]))
    except (ValueError, json.JSONDecodeError):
        return {}


def guardar_estado(service, estado):
    upsert_text_file(
        service, CURSALAB_FOLDER_ID, ESTADO_NOMBRE,
        json.dumps(estado), mime_type="application/json"
    )


def main():
    if not CURSALAB_FOLDER_ID:
        raise ValueError("La variable de entorno 'GDRIVE_CURSALAB_FOLDER_ID' no está configurada.")

    faltantes = [marca for marca, folder_id in DESTINOS.items() if not folder_id]
    if faltantes:
        raise ValueError(f"Faltan los folder IDs de destino para: {faltantes}")

    service = get_drive_service()
    estado = cargar_estado(service)

    print("Listando archivos en 'archivos cursalab'...")
    query = f"'{CURSALAB_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])

    # Las subcarpetas y el propio archivo de estado no son candidatos a distribuir.
    archivos = [
        f for f in files
        if f.get("mimeType") != "application/vnd.google-apps.folder" and f["name"] != ESTADO_NOMBRE
    ]

    if not archivos:
        print("No hay archivos pendientes en 'archivos cursalab'.")
        return

    candidatos_por_marca = defaultdict(list)
    sin_identificar = []
    ignorados = []
    for archivo in archivos:
        if not es_archivo_segmentacion(archivo["name"]):
            ignorados.append(archivo["name"])
            continue

        marca = detectar_marca(archivo["name"])
        if marca is None:
            sin_identificar.append(archivo["name"])
            continue
        candidatos_por_marca[marca].append(archivo)

    # Como ahora se COPIA (el original se queda en Cursalab para siempre), hay
    # que recordar que archivo ya se distribuyo para no volver a copiarlo cada
    # vez que corre este script. Si el "mas reciente" de una marca cambia (una
    # Segmentacion nueva de un dia distinto), se detecta por su ID y se vuelve
    # a copiar, reemplazando lo que hubiera en Inputs.
    for marca, candidatos in candidatos_por_marca.items():
        candidatos.sort(key=clave_de_orden)
        mas_reciente = candidatos[-1]
        anteriores = candidatos[:-1]

        if estado.get(marca) == mas_reciente["id"]:
            print(f"Sin novedad para {marca}: '{mas_reciente['name']}' ya fue distribuido antes.")
            continue

        destino_id = DESTINOS[marca]
        reemplazar_segmentacion_en_inputs(service, destino_id)
        copy_file(service, mas_reciente["id"], destino_id)
        print(f"Copiado: '{mas_reciente['name']}' -> Inputs de {marca}")

        estado[marca] = mas_reciente["id"]

        for viejo in anteriores:
            print(
                f"Aviso: '{viejo['name']}' es una Segmentación de {marca} más antigua "
                "que la que se acaba de copiar; se deja intacta en 'archivos cursalab'."
            )

    guardar_estado(service, estado)

    if sin_identificar:
        print(
            "Aviso: no se pudo identificar la marca de estos archivos de Segmentación, "
            f"se dejaron sin copiar para revisión manual: {sin_identificar}"
        )

    if ignorados:
        print(
            "Ignorados (no son archivos de Segmentación, se dejan intactos): "
            f"{ignorados}"
        )

    print("Distribución de segmentaciones completada.")


if __name__ == "__main__":
    main()
