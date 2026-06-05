"""
FastAPI backend for the React RAG UI.

Start:
    python3 -m uvicorn backend_api:app --reload --port 8000
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_prototype import (
    SCRIPT_DIR,
    ask,
    ask_with_sources,
    build_supabase_client,
    get_student_profile,
    ingest,
)


app = FastAPI(title="Uni Service-Bot API")

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


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_friendly_error(exc: Exception) -> str:
    message = str(exc)

    if "public.documents" in message or "PGRST205" in message:
        return (
            "Supabase table 'documents' was not found. Run "
            "01_supabase_pgvector.sql in the Supabase SQL Editor first, then "
            "index the FAQ again."
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
        result = ask_with_sources(question, student_id=request.student_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return result


@app.get("/api/students/{student_id}")
def read_student(student_id: str) -> dict:
    try:
        profile = get_student_profile(student_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    return profile


@app.get("/api/students/{student_id}/chats")
def list_student_chats(student_id: str) -> list[dict]:
    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .select("id, title, meta, updated_at, pinned")
            .eq("student_id", student_id)
            .is_("deleted_at", "null")
            .is_("archived_at", "null")
            .order("pinned", desc=True)
            .order("updated_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return response.data


@app.post("/api/chats")
def create_chat(request: ChatCreateRequest) -> dict:
    chat_id = str(uuid4())
    payload = {
        "id": chat_id,
        "student_id": request.student_id,
        "title": request.title,
        "meta": request.meta,
        "messages": request.messages,
        "updated_at": utc_timestamp(),
    }

    try:
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
    # Soft delete: hidden in the UI, retained for audit/demo recovery.
    now = utc_timestamp()

    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .update({"deleted_at": now, "updated_at": now})
            .eq("id", chat_id)
            .is_("deleted_at", "null")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return {"status": "deleted"}
