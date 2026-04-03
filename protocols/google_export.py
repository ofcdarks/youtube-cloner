"""
Google Export - Exporta resultados para Google Drive, Docs e Sheets.
Credentials loaded from environment variables or files (not committed to repo).
"""

import json
import os
import logging
from pathlib import Path
from datetime import datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger("ytcloner.google_export")

PROJECT_DIR = Path(__file__).parent.parent
CREDENTIALS_PATH = PROJECT_DIR / "credentials.json"
TOKEN_PATH = PROJECT_DIR / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def get_credentials():
    """Authenticate via OAuth. Uses env vars or files for credentials."""
    creds = None

    # Try loading token from env var first (for Docker/production)
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    if token_json:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load token from env: {e}")

    # Fall back to file
    if not creds and TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    "Google credentials not found. Copy credentials.json.example to credentials.json "
                    "and fill in your OAuth client ID/secret, or set GOOGLE_TOKEN_JSON env var."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=8090)

        # Save refreshed/new token
        try:
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            pass

    return creds


def get_drive_service():
    return build("drive", "v3", credentials=get_credentials())


# ── Google Drive ──────────────────────────────────────────

def create_folder(name: str, parent_id: str = None) -> str:
    """Cria uma pasta no Google Drive. Retorna o ID."""
    drive = get_drive_service()
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive.files().create(body=metadata, fields="id").execute()
    folder_id = folder["id"]
    print(f"  Pasta criada: https://drive.google.com/drive/folders/{folder_id}")
    return folder_id


def upload_file(file_path: str, folder_id: str = None, mime_type: str = "text/markdown") -> str:
    """Faz upload de um arquivo para o Drive. Retorna o ID."""
    drive = get_drive_service()
    path = Path(file_path)
    metadata = {"name": path.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(str(path), mimetype=mime_type)
    f = drive.files().create(body=metadata, media_body=media, fields="id").execute()
    file_id = f["id"]
    print(f"  Upload: {path.name} -> https://drive.google.com/file/d/{file_id}")
    return file_id


# ── Google Docs ───────────────────────────────────────────

def create_doc(title: str, content: str, folder_id: str = None) -> str:
    """Cria um Google Doc via conversão de arquivo de texto. Retorna o ID."""
    import tempfile
    drive = get_drive_service()

    tmp_path = str(PROJECT_DIR / "output" / "_tmp_doc.txt")
    Path(tmp_path).write_text(content, encoding="utf-8")

    metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(tmp_path, mimetype="text/plain")
    result = drive.files().create(body=metadata, media_body=media, fields="id").execute()
    doc_id = result["id"]

    try:
        Path(tmp_path).unlink()
    except Exception:
        pass

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"  Doc criado: {title} -> {url}")
    return doc_id


# ── Google Sheets ─────────────────────────────────────────

def create_sheet(title: str, data: list[list], folder_id: str = None) -> str:
    """Cria uma Google Sheet via CSV convertido. data = lista de linhas. Retorna o ID."""
    import csv
    drive = get_drive_service()

    tmp_path = str(PROJECT_DIR / "output" / "_tmp_sheet.csv")
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)

    metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(tmp_path, mimetype="text/csv")
    result = drive.files().create(body=metadata, media_body=media, fields="id").execute()
    sheet_id = result["id"]

    try:
        Path(tmp_path).unlink()
    except Exception:
        pass

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    print(f"  Sheet criada: {title} -> {url}")
    return sheet_id


# ── Export Completo ───────────────────────────────────────

def export_project(project_name: str, files: dict) -> dict:
    """
    Exporta todo o projeto para o Google Drive.

    files = {
        "sop": "caminho/do/sop.md",
        "niches": "caminho/dos/niches.md",
        "ideas": "caminho/das/ideas.md",
        "scripts": ["roteiro1.md", "roteiro2.md", ...],
        "video_ideas": [["Título", "Hook", "Nicho"], ...],  # para Sheet
    }
    """
    print("=" * 60)
    print("  GOOGLE EXPORT - Enviando para seu Google Drive")
    print("=" * 60)

    # 1. Criar pasta principal
    timestamp = datetime.now().strftime("%Y-%m-%d")
    folder_name = f"YT Cloner - {project_name} ({timestamp})"
    print(f"\n[1/4] Criando pasta: {folder_name}")
    folder_id = create_folder(folder_name)

    results = {"folder_id": folder_id, "docs": {}, "sheets": {}}

    # 2. SOPs como Google Doc
    print("\n[2/4] Criando Google Docs...")
    if files.get("sop") and Path(files["sop"]).exists():
        content = Path(files["sop"]).read_text(encoding="utf-8")
        doc_id = create_doc(f"SOP - {project_name}", content, folder_id)
        results["docs"]["sop"] = doc_id

    if files.get("niches") and Path(files["niches"]).exists():
        content = Path(files["niches"]).read_text(encoding="utf-8")
        doc_id = create_doc(f"Nichos - {project_name}", content, folder_id)
        results["docs"]["niches"] = doc_id

    if files.get("ideas") and Path(files["ideas"]).exists():
        content = Path(files["ideas"]).read_text(encoding="utf-8")
        doc_id = create_doc(f"Ideias de Vídeos - {project_name}", content, folder_id)
        results["docs"]["ideas"] = doc_id

    # 3. Roteiros como Google Docs
    print("\n[3/4] Exportando roteiros...")
    for i, script_path in enumerate(files.get("scripts", []), 1):
        if Path(script_path).exists():
            content = Path(script_path).read_text(encoding="utf-8")
            doc_id = create_doc(f"Roteiro {i} - {project_name}", content, folder_id)
            results["docs"][f"script_{i}"] = doc_id

    # 4. Ideias como Google Sheet
    print("\n[4/4] Criando planilha de ideias...")
    if files.get("video_ideas"):
        header = ["#", "Título", "Hook (30s)", "Resumo", "Nicho", "Prioridade"]
        data = [header] + files["video_ideas"]
        sheet_id = create_sheet(f"Ideias de Vídeos - {project_name}", data, folder_id)
        results["sheets"]["ideas"] = sheet_id

    print(f"\n{'=' * 60}")
    print(f"  EXPORT CONCLUÍDO!")
    print(f"  Pasta: https://drive.google.com/drive/folders/{folder_id}")
    print(f"  Docs: {len(results['docs'])}")
    print(f"  Sheets: {len(results['sheets'])}")
    print(f"{'=' * 60}")

    return results


# ── Teste rápido ──────────────────────────────────────────

if __name__ == "__main__":
    print("Testando conexão OAuth com Google Drive...")
    try:
        drive = get_drive_service()
        about = drive.about().get(fields="user,storageQuota").execute()
        email = about["user"]["emailAddress"]
        used = int(about["storageQuota"].get("usage", 0)) / 1024**3
        limit = int(about["storageQuota"].get("limit", 0)) / 1024**3
        print(f"Conectado como: {email}")
        print(f"Armazenamento: {used:.1f} GB / {limit:.0f} GB")
        print("Google Drive: OK")
    except Exception as e:
        print(f"Erro: {e}")
