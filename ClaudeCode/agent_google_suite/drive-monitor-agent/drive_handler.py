# drive-monitor-agent/drive_handler.py
import io
import logging
import time
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

import claude_processor

logger = logging.getLogger(__name__)

REPORTS_FOLDER_NAME = "_AgentReports"
MAX_RETRIES = 3


def _retry(fn, *args, **kwargs):
    """Call fn with retries on 429/5xx errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _get_or_create_reports_folder(service) -> str:
    """Find or create _AgentReports folder, return its ID."""
    query = f"name='{REPORTS_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = _retry(
        service.files().list(q=query, fields="files(id, name)").execute
    )
    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info(f"Found existing {REPORTS_FOLDER_NAME} folder: {folder_id}")
        return folder_id

    # Create folder
    metadata = {
        "name": REPORTS_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = _retry(service.files().create(body=metadata, fields="id").execute)
    folder_id = folder["id"]
    logger.info(f"Created {REPORTS_FOLDER_NAME} folder: {folder_id}")
    return folder_id


def _download_file_content(service, file_id: str, mime_type: str) -> str:
    """Download file content as text. Returns empty string on failure."""
    try:
        # Google Docs → export as plain text
        if mime_type == "application/vnd.google-apps.document":
            request = service.files().export_media(fileId=file_id, mimeType="text/plain")
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            request = service.files().export_media(fileId=file_id, mimeType="text/csv")
        elif mime_type in ("text/plain", "text/csv", "text/markdown"):
            request = service.files().get_media(fileId=file_id)
        elif mime_type == "application/pdf":
            # PDFs: download raw bytes, return placeholder
            return "[Archivo PDF — contenido no extraíble en texto plano]"
        else:
            return f"[Tipo de archivo no soportado: {mime_type}]"

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        return ""


def _upload_report(service, folder_id: str, report_name: str, content: str):
    """Upload a markdown report to _AgentReports folder."""
    from googleapiclient.http import MediaInMemoryUpload

    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
    metadata = {"name": report_name, "parents": [folder_id]}
    _retry(service.files().create(body=metadata, media_body=media, fields="id").execute)
    logger.info(f"Uploaded report: {report_name}")


def check_drive(creds, state: dict) -> str | None:
    """
    Check Drive for new/modified files since last check.
    Summarizes each with Claude and uploads a report to _AgentReports.
    Returns updated reports_folder_id (or None on total failure).
    """
    try:
        service = build("drive", "v3", credentials=creds)

        # Ensure _AgentReports folder exists
        folder_id = state.get("drive_reports_folder_id")
        if not folder_id:
            folder_id = _get_or_create_reports_folder(service)

        last_check = state.get("last_drive_check", "2000-01-01T00:00:00Z")
        logger.info(f"Drive check — files modified since {last_check}")

        # List files modified since last check, excluding _AgentReports folder itself
        query = (
            f"modifiedTime > '{last_check}' "
            f"and trashed = false "
            f"and '{folder_id}' not in parents"
        )
        all_files = []
        page_token = None
        while True:
            list_kwargs = dict(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageSize=50,
                orderBy="modifiedTime desc",
            )
            if page_token:
                list_kwargs["pageToken"] = page_token
            results = _retry(service.files().list(**list_kwargs).execute)
            all_files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        files = all_files
        logger.info(f"Found {len(files)} new/modified files")

        if not files:
            return folder_id

        report_lines = [
            f"# Drive Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Files processed: {len(files)}",
            "",
        ]

        for f in files:
            name = f["name"]
            file_id = f["id"]
            mime = f["mimeType"]
            modified = f["modifiedTime"]
            logger.info(f"Processing: {name} ({mime})")

            content = _download_file_content(service, file_id, mime)
            if content:
                result = claude_processor.summarize_file(name, content)
                summary = result.get("summary", "")
                topic = result.get("topic", "Desconocido")
            else:
                summary = "No se pudo leer el contenido."
                topic = "Desconocido"

            report_lines += [
                f"## {name}",
                f"- **Tema:** {topic}",
                f"- **Modificado:** {modified}",
                f"- **Resumen:** {summary}",
                "",
            ]

        report_content = "\n".join(report_lines)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _upload_report(service, folder_id, f"report_{ts}.md", report_content)

        return folder_id

    except Exception as e:
        logger.error(f"Drive check failed: {e}")
        return state.get("drive_reports_folder_id")
