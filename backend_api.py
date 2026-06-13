"""
FastAPI backend for the React RAG UI.

Start:
    python3 -m uvicorn backend_api:app --reload --port 8000
"""

from __future__ import annotations

from io import BytesIO
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_prototype import (
    SCRIPT_DIR,
    ask,
    ask_with_sources,
    build_supabase_client,
    get_knowledge_documents,
    get_professors,
    get_student_profile,
    ingest,
    index_uploaded_text,
)


app = FastAPI(title="MIA Studierendenservice API")
CHAT_RETENTION_DAYS = int(os.getenv("CHAT_RETENTION_DAYS", "30"))
MAX_VISIBLE_CHATS = int(os.getenv("MAX_VISIBLE_CHATS", "20"))
CHAT_UPLOAD_BUCKET = os.getenv("CHAT_UPLOAD_BUCKET", "chat-uploads")
MAX_ATTACHMENTS_PER_CHAT = int(os.getenv("MAX_ATTACHMENTS_PER_CHAT", "5"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
SUPPORTED_UPLOAD_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/webp",
}

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    student_id: str = "demo-student-001"
    chat_id: str | None = None


class IngestRequest(BaseModel):
    file_path: str | None = None


class ChatCreateRequest(BaseModel):
    student_id: str
    title: str
    meta: str = "gerade eben"
    messages: list[dict]


class ChatUpdateRequest(BaseModel):
    title: str | None = None
    meta: str = "gerade eben"
    messages: list[dict]


class ChatRenameRequest(BaseModel):
    title: str


class ChatPinRequest(BaseModel):
    pinned: bool


def safe_file_name(file_name: str) -> str:
    cleaned_name = Path(file_name).name.strip() or "upload"
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", cleaned_name)[:120]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def anonymized_chat_payload(now: str) -> dict:
    return {
        "title": "Gelöschter Chat",
        "meta": "anonymisiert",
        "messages": [],
        "pinned": False,
        "deleted_at": now,
        "updated_at": now,
    }


def create_chat_record(student_id: str, title: str, messages: list[dict]) -> dict:
    chat_id = str(uuid4())
    payload = {
        "id": chat_id,
        "student_id": student_id,
        "title": title[:80],
        "meta": "gerade eben",
        "messages": messages,
        "updated_at": utc_timestamp(),
    }
    response = build_supabase_client().table("chat_sessions").insert(payload).execute()
    return response.data[0]


def update_chat_messages(chat_id: str, messages: list[dict]) -> dict:
    response = (
        build_supabase_client()
        .table("chat_sessions")
        .update({"messages": messages, "meta": "gerade eben", "updated_at": utc_timestamp()})
        .eq("id", chat_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")
    return response.data[0]


def cleanup_expired_chats(student_id: str) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=CHAT_RETENTION_DAYS)
    now = utc_timestamp()

    (
        build_supabase_client()
        .table("chat_sessions")
        .update(anonymized_chat_payload(now))
        .eq("student_id", student_id)
        .is_("deleted_at", "null")
        .lt("updated_at", cutoff.isoformat())
        .execute()
    )


def user_friendly_error(exc: Exception) -> str:
    message = str(exc)

    if "public.documents" in message or "PGRST205" in message:
        return (
            "Supabase table 'documents' was not found. Run "
            "01_supabase_pgvector.sql in the Supabase SQL Editor first, then "
            "index the FAQ again."
        )

    if "public.chat_attachments" in message:
        return (
            "Supabase table 'chat_attachments' was not found. Run the updated "
            "01_supabase_pgvector.sql in the Supabase SQL Editor first."
        )

    if "permission denied" in message.lower() or "row-level security" in message.lower():
        return (
            "Supabase rejected the request. For this prototype, use a service "
            "role key or relax the table policy while testing locally."
        )

    if "must be owner of table documents" in message.lower():
        return (
            "Supabase RLS/ownership is blocking the app key. Your rows may exist "
            "in the SQL Editor, but the local API cannot read them. Use the real "
            "Supabase service_role secret key in .env as SUPABASE_SERVICE_ROLE_KEY, "
            "or recreate the match_documents function as table owner."
        )

    if "embedding" in message.lower() and "not_found" in message.lower():
        return (
            "The configured Gemini embedding model is not available for this "
            "API key. The prototype is configured for gemini-embedding-001."
        )

    return message


def extract_text_from_upload(file_bytes: bytes, mime_type: str, file_name: str) -> str:
    if mime_type in {"text/plain", "text/markdown", "text/csv"} or file_name.lower().endswith(
        (".txt", ".md", ".csv")
    ):
        return file_bytes.decode("utf-8", errors="ignore").strip()

    if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "PDF text extraction requires pypdf. Run pip install -r requirements.txt."
            ) from exc

        reader = PdfReader(BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()

    return ""


def get_chat_attachment_count(chat_id: str) -> int:
    response = (
        build_supabase_client()
        .table("chat_attachments")
        .select("id", count="exact")
        .eq("chat_id", chat_id)
        .execute()
    )
    return int(response.count or 0)


def create_storage_bucket_if_missing() -> None:
    client = build_supabase_client()
    try:
        buckets = client.storage.list_buckets()
        if any(
            (
                getattr(bucket, "name", None)
                or (bucket.get("name") if isinstance(bucket, dict) else None)
            )
            == CHAT_UPLOAD_BUCKET
            for bucket in buckets
        ):
            return
        client.storage.create_bucket(
            CHAT_UPLOAD_BUCKET,
            options={
                "public": False,
                "file_size_limit": MAX_UPLOAD_BYTES,
                "allowed_mime_types": sorted(SUPPORTED_UPLOAD_MIME_TYPES),
            },
        )
    except Exception:
        # The SQL setup also creates the bucket. If creation is blocked, the
        # later upload call will return the concrete Storage error.
        return


def signed_storage_url(storage_path: str) -> str | None:
    try:
        response = (
            build_supabase_client()
            .storage
            .from_(CHAT_UPLOAD_BUCKET)
            .create_signed_url(storage_path, 3600)
        )
        if isinstance(response, dict):
            return response.get("signedURL") or response.get("signedUrl")
        return getattr(response, "signed_url", None) or getattr(response, "signedURL", None)
    except Exception:
        return None


def get_chat_attachment_context(chat_id: str | None) -> str:
    if not chat_id:
        return ""

    response = (
        build_supabase_client()
        .table("chat_attachments")
        .select("file_name, extracted_text, status")
        .eq("chat_id", chat_id)
        .in_("status", ["indexed", "stored"])
        .order("created_at", desc=True)
        .limit(MAX_ATTACHMENTS_PER_CHAT)
        .execute()
    )
    blocks = []
    for attachment in response.data or []:
        extracted_text = (attachment.get("extracted_text") or "").strip()
        if not extracted_text:
            continue
        blocks.append(
            f"[Chat-Anhang: {attachment.get('file_name')}]\n"
            f"{extracted_text[:3000]}"
        )
    return "\n\n".join(blocks)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/ingest")
def ingest_document(request: IngestRequest) -> dict[str, str]:
    faq_path = Path(request.file_path) if request.file_path else SCRIPT_DIR / "uni_faq.txt"

    try:
        ingest(faq_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return {"message": f"FAQ indexed from {faq_path.name}."}


@app.post("/api/ask")
def ask_question(request: AskRequest) -> dict[str, object]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        attachment_context = get_chat_attachment_context(request.chat_id)
        result = ask_with_sources(
            question,
            student_id=request.student_id,
            attachment_context=attachment_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return result


@app.post("/api/chats/upload")
async def upload_chat_attachment(
    student_id: str = Form(...),
    chat_id: str | None = Form(None),
    messages_json: str = Form("[]"),
    file: UploadFile = File(...),
) -> dict[str, object]:
    file_name = safe_file_name(file.filename or "upload")
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in SUPPORTED_UPLOAD_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dateityp nicht unterstützt. Erlaubt sind PDF, TXT, Markdown, CSV, "
                "PNG, JPEG und WEBP."
            ),
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Datei ist zu groß. Maximal erlaubt sind {MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
        )

    try:
        messages = json.loads(messages_json)
        if not isinstance(messages, list):
            messages = []
    except json.JSONDecodeError:
        messages = []

    try:
        cleanup_expired_chats(student_id)
        if chat_id:
            existing_response = (
                build_supabase_client()
                .table("chat_sessions")
                .select("id, messages")
                .eq("id", chat_id)
                .eq("student_id", student_id)
                .is_("deleted_at", "null")
                .limit(1)
                .execute()
            )
            if not existing_response.data:
                raise HTTPException(status_code=404, detail="Saved chat not found.")
        else:
            created_chat = create_chat_record(
                student_id,
                f"Dateiupload: {file_name}",
                messages,
            )
            chat_id = created_chat["id"]

        if get_chat_attachment_count(chat_id) >= MAX_ATTACHMENTS_PER_CHAT:
            raise HTTPException(
                status_code=400,
                detail=f"Maximal {MAX_ATTACHMENTS_PER_CHAT} Anhänge pro Chat erlaubt.",
            )

        attachment_id = str(uuid4())
        storage_path = f"{student_id}/{chat_id}/{attachment_id}-{file_name}"
        create_storage_bucket_if_missing()
        build_supabase_client().storage.from_(CHAT_UPLOAD_BUCKET).upload(
            storage_path,
            file_bytes,
            {
                "content-type": mime_type,
                "x-upsert": "false",
            },
        )

        extracted_text = extract_text_from_upload(file_bytes, mime_type, file_name)
        source_label = f"Upload: {file_name} · Chat-Kontext"
        indexed_chunk_count = 0
        status = "unsupported"
        if extracted_text:
            indexed_chunk_count = index_uploaded_text(
                extracted_text,
                source_name=file_name,
                source_label=source_label,
                chat_id=chat_id,
                attachment_id=attachment_id,
            )
            status = "indexed" if indexed_chunk_count else "stored"
            if indexed_chunk_count:
                (
                    build_supabase_client()
                    .table("knowledge_documents")
                    .upsert(
                        {
                            "title": file_name,
                            "source_label": source_label,
                            "document_type": "chat_upload",
                            "status": "active",
                            "version": "upload",
                            "chunk_count": indexed_chunk_count,
                            "last_indexed_at": utc_timestamp(),
                        },
                        on_conflict="source_label",
                    )
                    .execute()
                )
        elif mime_type.startswith("image/"):
            status = "stored"

        attachment_payload = {
            "id": attachment_id,
            "chat_id": chat_id,
            "student_id": student_id,
            "file_name": file_name,
            "storage_bucket": CHAT_UPLOAD_BUCKET,
            "storage_path": storage_path,
            "mime_type": mime_type,
            "file_size": len(file_bytes),
            "status": status,
            "extracted_text": extracted_text[:12000] if extracted_text else None,
            "indexed_chunk_count": indexed_chunk_count,
        }
        attachment_response = (
            build_supabase_client()
            .table("chat_attachments")
            .insert(attachment_payload)
            .execute()
        )
        attachment = attachment_response.data[0]

        upload_message = {
            "role": "user",
            "text": f"Datei hochgeladen: {file_name}",
            "attachments": [
                {
                    "id": attachment_id,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "file_size": len(file_bytes),
                    "status": status,
                    "indexed_chunk_count": indexed_chunk_count,
                    "url": signed_storage_url(storage_path),
                }
            ],
        }
        updated_messages = [*messages, upload_message]
        update_chat_messages(chat_id, updated_messages)

        return {
            "chat_id": chat_id,
            "message": upload_message,
            "attachment": {
                **attachment,
                "url": signed_storage_url(storage_path),
            },
            "max_attachments": MAX_ATTACHMENTS_PER_CHAT,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc


@app.get("/api/students/{student_id}")
def read_student(student_id: str) -> dict:
    try:
        profile = get_student_profile(student_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    return profile


@app.get("/api/professors")
def list_professors() -> list[dict]:
    try:
        return get_professors()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc


@app.get("/api/knowledge-documents")
def list_knowledge_documents() -> list[dict]:
    try:
        return get_knowledge_documents()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc


@app.get("/api/students/{student_id}/chats")
def list_student_chats(student_id: str) -> list[dict]:
    try:
        cleanup_expired_chats(student_id)
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .select("id, title, meta, updated_at, pinned")
            .eq("student_id", student_id)
            .is_("deleted_at", "null")
            .is_("archived_at", "null")
            .order("pinned", desc=True)
            .order("updated_at", desc=True)
            .limit(MAX_VISIBLE_CHATS)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return response.data


@app.post("/api/chats")
def create_chat(request: ChatCreateRequest) -> dict:
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Chat title must not be empty.")

    chat_id = str(uuid4())
    payload = {
        "id": chat_id,
        "student_id": request.student_id,
        "title": title[:80],
        "meta": request.meta,
        "messages": request.messages,
        "updated_at": utc_timestamp(),
    }

    try:
        cleanup_expired_chats(request.student_id)
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .insert(payload)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return response.data[0]


@app.get("/api/chats/{chat_id}")
def read_chat(chat_id: str) -> dict:
    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .select("id, title, meta, messages, pinned")
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return response.data[0]


@app.patch("/api/chats/{chat_id}")
def update_chat(chat_id: str, request: ChatUpdateRequest) -> dict:
    payload = {
        "meta": request.meta,
        "messages": request.messages,
        "updated_at": utc_timestamp(),
    }
    if request.title:
        payload["title"] = request.title

    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update(payload)
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return response.data[0]


@app.patch("/api/chats/{chat_id}/rename")
def rename_chat(chat_id: str, request: ChatRenameRequest) -> dict:
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Chat title must not be empty.")
    title = title[:80]

    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update({"title": title, "updated_at": utc_timestamp()})
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return response.data[0]


@app.patch("/api/chats/{chat_id}/pin")
def pin_chat(chat_id: str, request: ChatPinRequest) -> dict:
    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update({"pinned": request.pinned, "updated_at": utc_timestamp()})
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return response.data[0]


@app.post("/api/chats/{chat_id}/archive")
def archive_chat(chat_id: str) -> dict[str, str]:
    now = utc_timestamp()

    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update({"archived_at": now, "updated_at": now})
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return {"status": "archived"}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict[str, str]:
    # Keep the row for auditability, but remove user-written content.
    now = utc_timestamp()

    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update(anonymized_chat_payload(now))
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return {"status": "deleted"}
