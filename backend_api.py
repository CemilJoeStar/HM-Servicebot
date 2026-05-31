"""
FastAPI backend for the React RAG UI.

Start:
    python3 -m uvicorn backend_api:app --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_prototype import (
    SCRIPT_DIR,
    ask,
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
def ask_question(request: AskRequest) -> dict[str, str]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        answer = ask(question, student_id=request.student_id, print_answer=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return {"answer": answer}


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
            .select("id, title, meta, updated_at")
            .eq("student_id", student_id)
            .order("updated_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    return response.data


@app.get("/api/chats/{chat_id}")
def read_chat(chat_id: str) -> dict:
    try:
        response = (
            build_supabase_client()
            .table("chat_sessions")
            .select("id, title, meta, messages")
            .eq("id", chat_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_friendly_error(exc)) from exc

    if not response.data:
        raise HTTPException(status_code=404, detail="Saved chat not found.")

    return response.data[0]
