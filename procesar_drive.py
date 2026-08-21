import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Importar funciones de lógica de negocio del script existente
from reporte_malla_pv import (
    procesar_estructura,
    procesar_capacitaciones,
    procesar_segmentacion,
    procesamiento_reporte,
    marcar_formato_invalido,
    marcar_posicion_retiro,
    marcar_personal_inactivo,
    marcar_ubicacion_central,
    ejecutar_limpieza_final_retiros,
    procesar_base_limpia,
    procesamiento_ciclos,
    FORMATOS_CONFIG
)
from drive_common import get_drive_service, find_or_create_subfolder, move_file

TZ_PERU = ZoneInfo("America/Lima")


def download_file(service, file_id, destination_path):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(destination_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        print(f"Descargando {destination_path}: {int(status.progress() * 100)}%")

def upload_file(service, file_path, folder_id):
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(
        file_path, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )
    file = service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id',
        supportsAllDrives=True
    ).execute()
    print(f"Reporte subido exitosamente a Google Drive con ID: {file.get('id')}")

def main():
    # Obtener IDs de carpetas desde las variables de entorno
    input_folder_id = os.environ.get("GDRIVE_INPUT_FOLDER_ID")
    output_folder_id = os.environ.get("GDRIVE_OUTPUT_FOLDER_ID")
    historial_folder_id = os.environ.get("GDRIVE_HISTORIAL_FOLDER_ID")
    # 'Makro' o 'PlazaVea': decide que hojas de DataaConsiderar2026 usar y a
    # que marca filtrar el reporte final. Cada marca corre en su propio
    # workflow de GitHub Actions, apuntando a sus propias carpetas de Drive.
    formato = os.environ.get("FORMATO", "Makro")
    if formato not in FORMATOS_CONFIG:
        raise ValueError(f"FORMATO invalido: {formato!r}. Debe ser uno de: {list(FORMATOS_CONFIG.keys())}")

    if not input_folder_id or not output_folder_id or not historial_folder_id:
        raise ValueError(
            "GDRIVE_INPUT_FOLDER_ID, GDRIVE_OUTPUT_FOLDER_ID y GDRIVE_HISTORIAL_FOLDER_ID deben estar configurados."
        )

    print("Iniciando conexión con Google Drive API...")
    service = get_drive_service()

    # Listar archivos en la carpeta de entrada
    print("Listando archivos en la carpeta de origen...")
    query = f"'{input_folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query, 
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])

    # Buscar archivos requeridos por patrón de nombre (equivalente a streamlit)
    file_ids = {}
    for file in files:
        name = file['name'].lower()
        if name.startswith('segment'):
            file_ids['segmentacion'] = (file['id'], file['name'])
        elif name.startswith('capacita'):
            file_ids['capacitacion'] = (file['id'], file['name'])
        elif name.startswith('9.- estructura'):
            file_ids['estructura'] = (file['id'], file['name'])
        elif name.startswith('dataaconsiderar'):
            file_ids['dataaconsiderar'] = (file['id'], file['name'])

    # 'dataaconsiderar' es un archivo base fijo: permanece siempre en Inputs y su sola
    # presencia no debe disparar el procesamiento. Los 3 insumos de ronda sí lo disparan.
    trigger_keys = ['segmentacion', 'capacitacion', 'estructura']
    base_keys = ['dataaconsiderar']

    # Procesamiento condicional: si no llegó ningún insumo de ronda, no se genera reporte
    if not any(k in file_ids for k in trigger_keys):
        print("No hay archivos pendientes en Inputs. No se genera reporte.")
        return

    # Si hay algunos insumos de ronda pero no todos, es un estado inválido que requiere atención
    missing_trigger = [k for k in trigger_keys if k not in file_ids]
    if missing_trigger:
        raise ValueError(f"Faltan archivos requeridos en la carpeta de Google Drive: {missing_trigger}")

    missing_base = [k for k in base_keys if k not in file_ids]
    if missing_base:
        raise ValueError(
            f"Falta el archivo base fijo en la carpeta de Google Drive: {missing_base}. "
            "Este archivo debe permanecer siempre en Inputs."
        )

    # Descargar archivos
    local_paths = {
        'segmentacion': 'segmentacion.xlsx',
        'capacitacion': 'capacitacion.xlsx',
        'estructura': 'estructura.xlsx',
        'dataaconsiderar': 'dataaconsiderar.xlsx'
    }

    for key, (file_id, original_name) in file_ids.items():
        print(f"Encontrado: {original_name}")
        download_file(service, file_id, local_paths[key])

    print("Procesando datos...")
    
    # Abrir archivos y ejecutar la lógica de procesamiento
    with open(local_paths['segmentacion'], 'rb') as file_seg, \
         open(local_paths['capacitacion'], 'rb') as file_cap, \
         open(local_paths['estructura'], 'rb') as file_est, \
         open(local_paths['dataaconsiderar'], 'rb') as file_data:

        print("Cargando y limpiando estructura...")
        df_est = procesar_estructura(file_est)
        
        print("Cargando y limpiando capacitaciones...")
        df_cap = procesar_capacitaciones(file_cap)
        
        print("Cargando y limpiando segmentación...")
        df_seg = procesar_segmentacion(file_seg)
        
        print(f"Ejecutando cruce de datos principal (formato: {formato})...")
        df_reporte, niveles_interes = procesamiento_reporte(df_est, df_cap, df_seg, file_data, formato=formato)

        print("Aplicando filtros de retiros...")
        filtros_a_aplicar = [
            marcar_formato_invalido,
            marcar_posicion_retiro,
            marcar_personal_inactivo,
            marcar_ubicacion_central,
            ejecutar_limpieza_final_retiros
        ]
        df_base_limpia = procesar_base_limpia(df_reporte, filtros_a_aplicar)

        print("Generando pestaña de Ciclos...")
        df_ciclos = procesamiento_ciclos(df_base_limpia, niveles_interes, formato=formato)

    # Guardar reporte resultante
    today_str = datetime.now(TZ_PERU).strftime('%Y-%m-%d')
    nombre_reporte = FORMATOS_CONFIG[formato]['nombre_reporte']
    output_filename = f"Reporte_Malla_{nombre_reporte}_{today_str}.xlsx"
    
    print(f"Guardando reporte localmente como '{output_filename}'...")
    import pandas as pd
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        df_ciclos.to_excel(writer, index=False, sheet_name='Ciclos')

    # Subir reporte a Google Drive
    print("Subiendo reporte a la carpeta de salida en Google Drive...")
    upload_file(service, output_filename, output_folder_id)

    # Archivar los insumos de ronda en Historial/YYYY-MM-DD/ y dejar Inputs limpia.
    # 'dataaconsiderar' NO se archiva: es un archivo base fijo que se conserva en Inputs
    # hasta que el usuario indique explícitamente reemplazarlo.
    print(f"Archivando insumos procesados en Historial/{today_str}/...")
    historial_subfolder_id = find_or_create_subfolder(service, historial_folder_id, today_str)
    for key, (file_id, original_name) in file_ids.items():
        if key in base_keys:
            continue
        move_file(service, file_id, input_folder_id, historial_subfolder_id)
        print(f"Archivado: {original_name}")
    print("DataaConsiderar2026 se conserva en Inputs (archivo base, no se archiva).")

    # Limpieza de archivos temporales descargados y generados localmente
    print("Limpiando archivos temporales...")
    for path in list(local_paths.values()) + [output_filename]:
        if os.path.exists(path):
            os.remove(path)

    print("¡Proceso completado exitosamente!")

if __name__ == "__main__":
    main()
