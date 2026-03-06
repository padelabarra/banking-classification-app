# drive-monitor-agent/claude_processor.py
import json
import logging
import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def summarize_file(filename: str, content: str) -> dict:
    """
    Summarize a Drive file and classify it by topic.
    Returns: {"summary": str, "topic": str}
    """
    if len(content) > 50000:
        content = content[:50000] + "\n\n[... contenido truncado ...]"

    prompt = f"""Analiza el siguiente archivo de Google Drive y proporciona:
1. Un resumen conciso (máximo 200 palabras)
2. Una categoría temática (ej: Finanzas, Trabajo, Personal, Tecnología, Salud, Legal, Educación, Otro)

Nombre del archivo: {filename}

Contenido:
{content}

Responde en formato JSON exacto:
{{"summary": "...", "topic": "..."}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Extract JSON even if there's surrounding text
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception as e:
        logger.error(f"Claude summarize_file error for {filename}: {e}")
        return {"summary": "Error al procesar con Claude.", "topic": "Desconocido"}


def classify_email(subject: str, sender: str, body: str) -> dict:
    """
    Classify an email and recommend an action.
    Returns: {"action": "archive"|"spam"|"important", "reason": str}
    """
    body_preview = body[:2000] if len(body) > 2000 else body

    prompt = f"""Analiza el siguiente email y decide qué hacer con él.

De: {sender}
Asunto: {subject}
Cuerpo: {body_preview}

Clasifícalo y elige UNA acción:
- "important": email importante que requiere atención (trabajo, personal relevante, facturas, citas)
- "archive": email informativo que no requiere acción (newsletters útiles, notificaciones, confirmaciones)
- "spam": publicidad no deseada, phishing, o correo basura

Responde en formato JSON exacto:
{{"action": "archive", "reason": "..."}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])
        if result.get("action") not in ("archive", "spam", "important"):
            result["action"] = "archive"
        return result
    except Exception as e:
        logger.error(f"Claude classify_email error: {e}")
        return {"action": "archive", "reason": "Error al clasificar, se archiva por seguridad."}
