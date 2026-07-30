import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from drive_common import (
    download_text,
    find_file_in_folder,
    find_or_create_spreadsheet,
    get_drive_service,
    get_sheets_service,
    upsert_text_file,
)

TZ_PERU = ZoneInfo("America/Lima")
BITACORA_NAME = "bitacora_revisiones.txt"
STATE_NAME = ".vigilancia_state.json"
ESTADO_SHEET_NAME = "Estado_Vigilancia"
INTERNAL_NAMES = {BITACORA_NAME.lower(), STATE_NAME.lower(), ESTADO_SHEET_NAME.lower()}


def construir_snapshot(files):
    relevantes = [f for f in files if f["name"].lower() not in INTERNAL_NAMES]
    return {f["id"]: f["modifiedTime"] for f in relevantes}


def determinar_estado(current_snapshot, previous_snapshot):
    # Solo cuentan como cambio los archivos presentes ahora cuyo id es nuevo o cuyo
    # modifiedTime difiere del último registrado. Un archivo que desaparece (p. ej.
    # porque el módulo de procesamiento acaba de archivarlo en Historial) NO cuenta
    # como cambio: evita un falso "CAMBIOS DETECTADOS" justo después de limpiar Inputs.
    for file_id, modified_time in current_snapshot.items():
        if previous_snapshot.get(file_id) != modified_time:
            return "CAMBIOS DETECTADOS (Archivos listos para procesar)"
    return "Sin cambios en Inputs"


def actualizar_bitacora(existing_content, today_str, timestamp_str, status):
    header_date = None
    if existing_content.strip():
        primera_linea = existing_content.splitlines()[0]
        match = re.search(r"\d{4}-\d{2}-\d{2}", primera_linea)
        if match:
            header_date = match.group(0)

    if not existing_content.strip() or header_date != today_str:
        nuevo_contenido = f"=== Bitácora de revisiones de Inputs - {today_str} ===\n"
    else:
        nuevo_contenido = existing_content
        if not nuevo_contenido.endswith("\n"):
            nuevo_contenido += "\n"

    nuevo_contenido += f"{timestamp_str} (hora Perú) - {status}\n"
    return nuevo_contenido


def escribir_estado_sheet(sheets_service, spreadsheet_id, timestamp_str, status):
    tab_name = "Estado"

    # No asumimos que la pestaña ya se llama "Estado" solo porque el archivo ya
    # existía: una corrida anterior pudo haber creado el archivo y fallado antes
    # de completar el renombrado. Se verifica el nombre real cada vez.
    metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    hojas = metadata.get("sheets", [])
    nombres_existentes = [h["properties"]["title"] for h in hojas]

    if tab_name not in nombres_existentes:
        primer_sheet_id = hojas[0]["properties"]["sheetId"]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": primer_sheet_id, "title": tab_name},
                    "fields": "title"
                }
            }]}
        ).execute()

    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!A1:B2",
        valueInputOption="RAW",
        body={"values": [
            ["Última revisión (hora Perú)", "Estado"],
            [timestamp_str, status]
        ]}
    ).execute()


def main():
    input_folder_id = os.environ.get("GDRIVE_INPUT_FOLDER_ID")
    if not input_folder_id:
        raise ValueError("La variable de entorno 'GDRIVE_INPUT_FOLDER_ID' no está configurada.")

    service = get_drive_service()

    results = service.files().list(
        q=f"'{input_folder_id}' in parents and trashed = false",
        fields="files(id, name, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])

    current_snapshot = construir_snapshot(files)

    state_file = find_file_in_folder(service, input_folder_id, STATE_NAME)
    previous_snapshot = {}
    if state_file:
        try:
            previous_snapshot = json.loads(download_text(service, state_file["id"]))
        except (ValueError, json.JSONDecodeError):
            previous_snapshot = {}

    status = determinar_estado(current_snapshot, previous_snapshot)

    now = datetime.now(TZ_PERU)
    today_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

    bitacora_file = find_file_in_folder(service, input_folder_id, BITACORA_NAME)
    existing_content = download_text(service, bitacora_file["id"]) if bitacora_file else ""

    nuevo_contenido = actualizar_bitacora(existing_content, today_str, timestamp_str, status)

    upsert_text_file(service, input_folder_id, BITACORA_NAME, nuevo_contenido)
    upsert_text_file(
        service, input_folder_id, STATE_NAME,
        json.dumps(current_snapshot), mime_type="application/json"
    )

    estado_spreadsheet_id, _ = find_or_create_spreadsheet(service, input_folder_id, ESTADO_SHEET_NAME)
    sheets_service = get_sheets_service()
    escribir_estado_sheet(sheets_service, estado_spreadsheet_id, timestamp_str, status)

    print(f"[{timestamp_str}] {status}")


if __name__ == "__main__":
    main()
