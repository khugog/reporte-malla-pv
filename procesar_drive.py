import os
import io
import json
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
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
    procesamiento_ciclos
)

def get_drive_service():
    creds_json = os.environ.get("GDRIVE_CREDENTIALS")
    if not creds_json:
        raise ValueError("La variable de entorno 'GDRIVE_CREDENTIALS' no está configurada.")
    
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        info, 
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

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
    
    if not input_folder_id or not output_folder_id:
        raise ValueError("GDRIVE_INPUT_FOLDER_ID y GDRIVE_OUTPUT_FOLDER_ID deben estar configurados.")

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

    if not files:
        print("No se encontraron archivos en la carpeta de origen.")
        return

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

    # Validar que todos los archivos requeridos estén presentes
    required_keys = ['segmentacion', 'capacitacion', 'estructura', 'dataaconsiderar']
    missing = [k for k in required_keys if k not in file_ids]
    if missing:
        raise ValueError(f"Faltan archivos requeridos en la carpeta de Google Drive: {missing}")

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
        
        print("Ejecutando cruce de datos principal...")
        df_reporte, niveles_interes = procesamiento_reporte(df_est, df_cap, df_seg, file_data)
        
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
        df_ciclos = procesamiento_ciclos(df_base_limpia, niveles_interes)

    # Guardar reporte resultante
    today = datetime.today().strftime('%Y-%m-%d')
    output_filename = f"Reporte_Malla_PlazaVea_{today}.xlsx"
    
    print(f"Guardando reporte localmente como '{output_filename}'...")
    import pandas as pd
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        df_ciclos.to_excel(writer, index=False, sheet_name='Ciclos')

    # Subir reporte a Google Drive
    print("Subiendo reporte a la carpeta de salida en Google Drive...")
    upload_file(service, output_filename, output_folder_id)

    # Limpieza de archivos temporales descargados y generados localmente
    print("Limpiando archivos temporales...")
    for path in list(local_paths.values()) + [output_filename]:
        if os.path.exists(path):
            os.remove(path)
            
    print("¡Proceso completado exitosamente!")

if __name__ == "__main__":
    main()
