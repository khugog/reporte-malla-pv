import io
import json
import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


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


def find_file_in_folder(service, folder_id, name):
    escaped_name = name.replace("'", "\\'")
    query = f"'{folder_id}' in parents and name = '{escaped_name}' and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])
    return files[0] if files else None


def download_text(service, file_id):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8")


def upsert_text_file(service, folder_id, name, content, mime_type="text/plain"):
    existing = find_file_in_folder(service, folder_id, name)
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=mime_type, resumable=False)
    if existing:
        service.files().update(
            fileId=existing["id"],
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return existing["id"]

    file_metadata = {"name": name, "parents": [folder_id]}
    created = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True
    ).execute()
    return created["id"]


def find_or_create_subfolder(service, parent_id, name):
    escaped_name = name.replace("'", "\\'")
    query = (
        f"'{parent_id}' in parents and name = '{escaped_name}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    created = service.files().create(
        body=metadata,
        fields="id",
        supportsAllDrives=True
    ).execute()
    return created["id"]


def move_file(service, file_id, current_parent_id, new_parent_id):
    service.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=current_parent_id,
        fields="id, parents",
        supportsAllDrives=True
    ).execute()
