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
    """Authenticate via web OAuth (DB token) or env var. No local browser needed.

    Priority:
    1. Web OAuth token from DB (set via /api/admin/gdrive/auth flow)
    2. GOOGLE_TOKEN_JSON env var
    3. Legacy token.json file
    """
    creds = None

    # Priority 1: Web OAuth token from DB
    try:
        from routes.gdrive_routes import get_oauth_credentials
        return get_oauth_credentials()
    except (ImportError, RuntimeError, Exception) as e:
        logger.debug(f"Web OAuth not available: {e}")

    # Priority 2: Env var
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    if token_json:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load token from env: {e}")

    # Priority 3: Legacy file
    if not creds and TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token
            try:
                TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass
        else:
            raise RuntimeError(
                "Google Drive nao conectado. Conecte via Admin Panel > Google Drive, "
                "ou defina GOOGLE_TOKEN_JSON nas env vars."
            )

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


# ── Admin Root Folder ────────────────────────────────────

_admin_root_id = None  # cached per-process


def get_admin_root_folder() -> str:
    """Get or create the admin root folder 'YT Cloner' in Google Drive.
    All project and student folders live inside this root.
    Cached per-process to avoid repeated API calls.
    """
    global _admin_root_id
    if _admin_root_id:
        return _admin_root_id

    # Check DB for saved root folder ID
    try:
        from database import get_setting, set_setting
        saved = get_setting("drive_admin_root_id")
        if saved:
            # Verify it still exists
            try:
                drive = get_drive_service()
                drive.files().get(fileId=saved, fields="id").execute()
                _admin_root_id = saved
                return saved
            except Exception:
                pass  # Folder deleted, recreate

        # Create root folder
        drive = get_drive_service()
        metadata = {
            "name": "YT Cloner",
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = drive.files().create(body=metadata, fields="id").execute()
        _admin_root_id = folder["id"]
        set_setting("drive_admin_root_id", _admin_root_id)
        logger.info(f"Admin root folder created: {_admin_root_id}")
        return _admin_root_id
    except Exception as e:
        logger.warning(f"Failed to get/create admin root folder: {e}")
        return ""


def get_or_create_project_folder(project_name: str) -> str:
    """Get or create a project folder inside the admin root. No duplicates."""
    root = get_admin_root_folder()
    if not root:
        return create_folder(f"YT Cloner - {project_name}")
    folder_name = f"Projeto - {project_name}"
    return find_or_create_subfolder(folder_name, root)


def get_or_create_student_folder(student_name: str) -> str:
    """Get or create a student folder inside the admin root. No duplicates."""
    root = get_admin_root_folder()
    if not root:
        return create_folder(f"YT Cloner - {student_name}")
    folder_name = f"Aluno - {student_name}"
    return find_or_create_subfolder(folder_name, root)


# ── Drive Helpers (Student Auto-Sync) ────────────────────


def share_folder(folder_id: str, email: str, role: str = "writer"):
    """Share a Drive folder with an email address."""
    drive = get_drive_service()
    try:
        drive.permissions().create(
            fileId=folder_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
        ).execute()
        logger.info(f"Shared folder {folder_id} with {email} ({role})")
    except Exception as e:
        logger.warning(f"Failed to share folder with {email}: {e}")


def delete_drive_file(file_id: str):
    """Delete a file from Google Drive."""
    try:
        drive = get_drive_service()
        drive.files().delete(fileId=file_id).execute()
        logger.info(f"Deleted Drive file: {file_id}")
    except Exception as e:
        logger.warning(f"Failed to delete Drive file {file_id}: {e}")


def find_or_create_subfolder(name: str, parent_id: str) -> str:
    """Find existing subfolder by name or create it. Returns folder ID."""
    drive = get_drive_service()
    # Search for existing folder
    query = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    # Create new
    return create_folder(name, parent_id)


def get_daily_folder(parent_id: str) -> str:
    """Get or create today's daily folder inside a parent folder."""
    today = datetime.now().strftime("%Y-%m-%d")
    return find_or_create_subfolder(today, parent_id)


def sync_file_to_drive(content: str, filename: str, label: str, folder_id: str) -> str:
    """Create/update a Google Doc in a Drive folder. Returns the doc ID."""
    if not content or not folder_id:
        return ""
    try:
        doc_id = create_doc(label, content, folder_id)
        return doc_id
    except Exception as e:
        logger.error(f"Failed to sync {filename} to Drive: {e}")
        return ""


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
