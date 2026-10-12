import json
import os
import re
import unicodedata

from drive_common import copy_file, download_text, find_file_in_folder, get_drive_service, trash_file, upsert_text_file

FECHA_EN_NOMBRE = re.compile(r"(\d{4}-\d{2}-\d{2})")
ESTADO_NOMBRE = ".distribucion_employees_state.json"

# Carpeta compartida donde se va dejando el archivo "employees" que aplica a
# TODAS las marcas (Makro, PlazaVea, Oslo, Merkao, etc.) por igual -- a
# diferencia de la Segmentación, este NO trae el nombre de una marca especifica
# en el archivo: es el mismo archivo el que debe llegar a las 4 mallas.
EMPLOYEES_FOLDER_ID = os.environ.get("GDRIVE_EMPLOYEES_FOLDER_ID")

# Carpeta "Inputs" de cada malla. Mismos secrets que ya usa cada workflow de
# reporte (run_report_*.yml) y distribuir_segmentaciones.py.
DESTINOS = {
    "Makro": os.environ.get("GDRIVE_INPUT_FOLDER_ID"),
    "PlazaVea": os.environ.get("GDRIVE_INPUT_FOLDER_ID_PLAZAVEA"),
    "Oslo": os.environ.get("GDRIVE_INPUT_FOLDER_ID_OSLO"),
    "Merkao": os.environ.get("GDRIVE_INPUT_FOLDER_ID_MERKAO"),
}


def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto


def es_archivo_employees(nombre_archivo):
    # Mismo criterio que usa procesar_drive.py para identificar este insumo
    # (prefijo 'employees' en el nombre). Evita tocar cualquier otro archivo
    # que caiga por error en esta carpeta compartida.
    return "employees" in normalizar(nombre_archivo)


def clave_de_orden(archivo):
    # Igual que en distribuir_segmentaciones.py: se usa la fecha del nombre
    # del archivo para saber cual es el mas reciente; si no trae fecha, se cae
    # de respaldo a la fecha de modificacion en Drive.
    match = FECHA_EN_NOMBRE.search(archivo["name"])
    fecha_nombre = match.group(1) if match else ""
    return (fecha_nombre, archivo.get("modifiedTime", ""))


def reemplazar_employees_en_inputs(service, folder_id):
    # Si ya hay un Employees de una ronda anterior sin procesar en Inputs, se
    # reemplaza por el nuevo (mismo criterio que se definio para Segmentación):
    # no se acumulan ni se bloquea la copia nueva.
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    for f in results.get("files", []):
        if f["name"].lower().startswith("employees"):
            trash_file(service, f["id"])
            print(f"Reemplazado: se eliminó el Employees anterior '{f['name']}' de Inputs.")


def cargar_estado(service):
    archivo_estado = find_file_in_folder(service, EMPLOYEES_FOLDER_ID, ESTADO_NOMBRE)
    if not archivo_estado:
        return {}
    try:
        return json.loads(download_text(service, archivo_estado["id"]))
    except (ValueError, json.JSONDecodeError):
        return {}


def guardar_estado(service, estado):
    upsert_text_file(
        service, EMPLOYEES_FOLDER_ID, ESTADO_NOMBRE,
        json.dumps(estado), mime_type="application/json"
    )


def main():
    if not EMPLOYEES_FOLDER_ID:
        raise ValueError("La variable de entorno 'GDRIVE_EMPLOYEES_FOLDER_ID' no está configurada.")

    faltantes = [marca for marca, folder_id in DESTINOS.items() if not folder_id]
    if faltantes:
        raise ValueError(f"Faltan los folder IDs de destino para: {faltantes}")

    service = get_drive_service()
    estado = cargar_estado(service)

    print("Listando archivos en la carpeta compartida de Employees...")
    query = f"'{EMPLOYEES_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])

    archivos = [
        f for f in files
        if f.get("mimeType") != "application/vnd.google-apps.folder" and f["name"] != ESTADO_NOMBRE
    ]

    candidatos = [f for f in archivos if es_archivo_employees(f["name"])]
    ignorados = [f["name"] for f in archivos if not es_archivo_employees(f["name"])]

    if not candidatos:
        print("No hay archivos de Employees pendientes en la carpeta compartida.")
        if ignorados:
            print(f"Ignorados (no son archivos de Employees, se dejan intactos): {ignorados}")
        return

    candidatos.sort(key=clave_de_orden)
    mas_reciente = candidatos[-1]
    anteriores = candidatos[:-1]

    if estado.get("ultimo_distribuido") == mas_reciente["id"]:
        print(f"Sin novedad: '{mas_reciente['name']}' ya fue distribuido a todas las mallas antes.")
        return

    for marca, destino_id in DESTINOS.items():
        reemplazar_employees_en_inputs(service, destino_id)
        copy_file(service, mas_reciente["id"], destino_id)
        print(f"Copiado: '{mas_reciente['name']}' -> Inputs de {marca}")

    estado["ultimo_distribuido"] = mas_reciente["id"]
    guardar_estado(service, estado)

    for viejo in anteriores:
        print(
            f"Aviso: '{viejo['name']}' es un Employees más antiguo "
            "que el que se acaba de copiar; se deja intacto en la carpeta compartida."
        )

    if ignorados:
        print(
            "Ignorados (no son archivos de Employees, se dejan intactos): "
            f"{ignorados}"
        )

    print("Distribución de Employees completada.")


if __name__ == "__main__":
    main()
