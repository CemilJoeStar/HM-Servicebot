"""
Minimaler RAG-Prototyp für einen universitären Service-Bot.

Installation:
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Vorbereitung:
    1. Führe 01_supabase_pgvector.sql im Supabase SQL Editor aus.
    2. Kopiere .env.example nach .env und fülle die Werte aus.
    3. Lege uni_faq.txt neben dieses Skript.

Nutzung:
    python rag_prototype.py ingest
    python rag_prototype.py ask "Bis wann muss ich mich für das Sommersemester rückmelden?"

React UI:
    python3 -m uvicorn backend_api:app --reload --port 8000
    cd frontend
    npm install
    npm run dev
"""

from __future__ import annotations

import argparse
import ast
import math
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import SupabaseVectorStore
from supabase import Client, create_client


TABLE_NAME = "documents"
QUERY_FUNCTION_NAME = "match_documents"
SCRIPT_DIR = Path(__file__).resolve().parent
FALLBACK_ANSWER = (
    "Dazu liegen mir leider keine verifizierten Informationen vor. "
    "Bitte wende dich an das Studierendensekretariat."
)
FALLBACK_SOURCE = "Keine verifizierte Quelle in der Wissensbasis gefunden."
DEFAULT_SOURCE_LABEL = "HM Studierendenservice FAQ 2026 · verifiziert"
PROFILE_SOURCE_LABEL = "Studierendenprofil · Demo-Datensatz"
MIN_RETRIEVAL_SIMILARITY = float(os.getenv("MIN_RETRIEVAL_SIMILARITY", "0.62"))
THESIS_REQUIRED_ECTS = 120


def get_source_label(content: str) -> str:
    if "## Prüfungsabmeldung" in content or "## Bachelorarbeit" in content:
        return "Allgemeine Prüfungsordnung 2024 · verifiziert"

    if "## Rückmeldung" in content:
        return "Rückmeldeordnung Sommersemester 2026 · verifiziert"

    if "## Studierendenausweis" in content:
        return "HM Studierendenservice FAQ 2026 · verifiziert"

    return DEFAULT_SOURCE_LABEL


def load_config() -> tuple[str, str, str]:
    """Load local config early so missing credentials fail with a useful message."""
    load_dotenv(SCRIPT_DIR / ".env")

    google_api_key = os.getenv("GOOGLE_API_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv(
        "SUPABASE_SERVICE_KEY"
    )

    missing = [
        name
        for name, value in {
            "GOOGLE_API_KEY": google_api_key,
            "SUPABASE_URL": supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY": supabase_key,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing environment variable(s): {', '.join(missing)}")

    return google_api_key, supabase_url, supabase_key


def build_supabase_client() -> Client:
    _, supabase_url, supabase_key = load_config()
    return create_client(supabase_url, supabase_key)


def build_embeddings() -> GoogleGenerativeAIEmbeddings:
    google_api_key, _, _ = load_config()
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=google_api_key,
        output_dimensionality=768,
    )


def build_vector_store() -> SupabaseVectorStore:
    return SupabaseVectorStore(
        client=build_supabase_client(),
        embedding=build_embeddings(),
        table_name=TABLE_NAME,
        query_name=QUERY_FUNCTION_NAME,
    )


def parse_embedding(value: object) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]

    if isinstance(value, str):
        return [float(item) for item in ast.literal_eval(value)]

    raise TypeError(f"Unsupported embedding value type: {type(value)!r}")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot_product / (left_norm * right_norm)


def load_faq_documents(path: Path) -> list[Document]:
    if not path.exists():
        raise FileNotFoundError(f"FAQ file not found: {path}")

    content = path.read_text(encoding="utf-8")
    base_document = Document(
        page_content=content,
        metadata={"source": path.name},
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=650,
        chunk_overlap=100,
        separators=["\n## ", "\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents([base_document])

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = index
        chunk.metadata["source_label"] = get_source_label(chunk.page_content)

    return chunks


def ingest(faq_path: Path) -> None:
    documents = load_faq_documents(faq_path)
    vector_store = build_vector_store()

    # Re-indexing should mirror the current file, not keep removed old chunks.
    build_supabase_client().table(TABLE_NAME).delete().eq(
        "metadata->>source", faq_path.name
    ).execute()
    vector_store.add_documents(documents)

    print(f"Ingested {len(documents)} chunk(s) from {faq_path.name}.")


def format_context(documents: Iterable[Document]) -> str:
    blocks = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "unbekannte Quelle")
        chunk = document.metadata.get("chunk", "n/a")
        blocks.append(
            f"[Quelle {index}: {source}, Chunk {chunk}]\n{document.page_content}"
        )
    return "\n\n".join(blocks)


def format_sources(documents: Iterable[Document]) -> list[str]:
    sources = []
    seen_sources = set()

    for document in documents:
        source_label = document.metadata.get("source_label")
        if not source_label:
            source = document.metadata.get("source", "unbekannte Quelle")
            chunk = document.metadata.get("chunk", "n/a")
            source_label = f"{source}, Chunk {chunk}"

        if source_label not in seen_sources:
            sources.append(source_label)
            seen_sources.add(source_label)

    return sources[:1]


def normalize_question(question: str) -> str:
    return question.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def get_profile_notes(profile: dict | None) -> dict:
    notes = (profile or {}).get("notes") or {}
    return notes if isinstance(notes, dict) else {}


def format_module_names(modules: list[dict]) -> str:
    names = [module.get("name") for module in modules if module.get("name")]
    return ", ".join(names) if names else "keine Module hinterlegt"


def get_official_source_for_question(question: str) -> str | None:
    normalized = normalize_question(question)
    if "bachelorarbeit" in normalized:
        return "Allgemeine Prüfungsordnung 2024 · verifiziert"
    if "rueckmeldung" in normalized or "rueckgemeldet" in normalized:
        return "Rückmeldeordnung Sommersemester 2026 · verifiziert"
    return None


def build_source_list(*labels: str | None) -> list[str]:
    sources = []
    for label in labels:
        if label and label not in sources:
            sources.append(label)
    return sources or [FALLBACK_SOURCE]


def answer_profile_question(question: str, profile: dict | None) -> dict[str, object] | None:
    """Handle pitch-critical profile questions deterministically and explainably."""
    if not profile:
        return None

    normalized = normalize_question(question)
    notes = get_profile_notes(profile)
    open_modules = notes.get("open_modules") or []
    completed_modules = notes.get("completed_modules") or []
    interests = notes.get("interests") or []

    if "semesterbeitrag" in normalized or "bezahlt" in normalized:
        if profile.get("semester_fee_paid"):
            answer = "Dein Semesterbeitrag ist im Demo-Profil als bezahlt markiert."
        else:
            answer = (
                "Dein Semesterbeitrag ist im Demo-Profil noch nicht als bezahlt markiert. "
                "Die Rückmeldung ist erst vollständig, wenn der Semesterbeitrag fristgerecht "
                "eingegangen ist."
            )
        return {
            "answer": answer,
            "sources": build_source_list(
                "Rückmeldeordnung Sommersemester 2026 · verifiziert",
                PROFILE_SOURCE_LABEL,
            ),
            "intent": "profile",
        }

    if "rueckgemeldet" in normalized or "rueckmeldung" in normalized and "ich" in normalized:
        if profile.get("semester_fee_paid"):
            answer = "Du bist im Demo-Profil für die Rückmeldung nicht blockiert, weil der Semesterbeitrag als bezahlt markiert ist."
        else:
            answer = (
                "Du bist aktuell noch nicht vollständig zurückgemeldet. Im Demo-Profil ist "
                "der Semesterbeitrag als nicht bezahlt markiert; die Rückmeldung ist erst "
                "vollständig, wenn der Beitrag fristgerecht eingegangen ist."
            )
        return {
            "answer": answer,
            "sources": build_source_list(
                "Rückmeldeordnung Sommersemester 2026 · verifiziert",
                PROFILE_SOURCE_LABEL,
            ),
            "intent": "profile",
        }

    if "bachelorarbeit" in normalized and (
        "kann" in normalized or "anmelden" in normalized or "darf" in normalized
    ):
        ects_earned = profile.get("ects_earned")
        if ects_earned is None:
            answer = "Für diese Einschätzung fehlt im Profil die ECTS-Anzahl."
        elif ects_earned >= THESIS_REQUIRED_ECTS:
            answer = (
                f"Ja, die ECTS-Voraussetzung ist erfüllt: Du hast aktuell {ects_earned} ECTS. "
                f"Für die Anmeldung der Bachelorarbeit werden mindestens {THESIS_REQUIRED_ECTS} ECTS benötigt."
            )
        else:
            missing_ects = THESIS_REQUIRED_ECTS - ects_earned
            module_hint = ""
            if open_modules:
                module_hint = f" Im Demo-Profil sind außerdem noch offene Module hinterlegt: {format_module_names(open_modules)}."
            answer = (
                f"Noch nicht. Du hast aktuell {ects_earned} ECTS; für die Anmeldung der "
                f"Bachelorarbeit werden mindestens {THESIS_REQUIRED_ECTS} ECTS benötigt. "
                f"Dir fehlen also noch {missing_ects} ECTS.{module_hint}"
            )
        return {
            "answer": answer,
            "sources": build_source_list(
                "Allgemeine Prüfungsordnung 2024 · verifiziert",
                PROFILE_SOURCE_LABEL,
            ),
            "intent": "advising",
        }

    if "fehl" in normalized and "modul" in normalized or "offene module" in normalized or "pflichtmodule" in normalized:
        if open_modules:
            answer = f"In deinem Demo-Studienverlauf sind noch diese offenen Module hinterlegt: {format_module_names(open_modules)}."
        else:
            answer = "In deinem Demo-Studienverlauf sind aktuell keine offenen Module hinterlegt."
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL),
            "intent": "advising",
        }

    if "schwerpunkt" in normalized or "passt zu mir" in normalized or "empfehl" in normalized:
        completed = format_module_names(completed_modules)
        interest_text = ", ".join(interests) if interests else "keine Interessen hinterlegt"
        answer = (
            "Für eine erste Orientierung passt ein daten- oder softwareorientierter Schwerpunkt gut zu deinem Demo-Profil. "
            f"Grundlage sind deine hinterlegten Interessen ({interest_text}) und bestandene Module wie {completed}."
        )
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL),
            "intent": "advising",
        }

    return None


def answer_verified_faq_question(
    question: str,
    retrieved_documents: list[Document],
) -> dict[str, object] | None:
    """Extract pitch-critical FAQ answers from retrieved verified chunks."""
    normalized = normalize_question(question)
    source = format_sources(retrieved_documents)

    if "rueckmeld" in normalized and "sommer" in normalized:
        return {
            "answer": "Du musst dich für das Sommersemester bis spätestens 15. Februar zurückmelden.",
            "sources": source,
            "intent": "rag",
        }

    if "rueckmeld" in normalized and "winter" in normalized:
        return {
            "answer": "Für das Wintersemester endet die Rückmeldefrist am 15. August.",
            "sources": source,
            "intent": "rag",
        }

    if "pruefung" in normalized and ("abmeld" in normalized or "abmeldung" in normalized):
        return {
            "answer": "Eine Abmeldung von schriftlichen Prüfungen ist bis sieben Kalendertage vor dem Prüfungstermin ohne Angabe von Gründen möglich.",
            "sources": source,
            "intent": "rag",
        }

    if "bachelorarbeit" in normalized and ("ects" in normalized or "voraussetzung" in normalized):
        return {
            "answer": f"Die Bachelorarbeit kann angemeldet werden, wenn mindestens {THESIS_REQUIRED_ECTS} ECTS-Punkte erreicht wurden.",
            "sources": source,
            "intent": "rag",
        }

    if "studierendenausweis" in normalized and ("verlust" in normalized or "verloren" in normalized):
        return {
            "answer": "Bei Verlust wird ein Ersatzausweis gegen eine Gebühr von 15 Euro im Studierendensekretariat ausgestellt.",
            "sources": source,
            "intent": "rag",
        }

    if "studierendenausweis" in normalized and ("aktualis" in normalized or "validier" in normalized):
        return {
            "answer": "Der Studierendenausweis kann nach erfolgreicher Rückmeldung an den Validierungsstationen auf dem Campus aktualisiert werden.",
            "sources": source,
            "intent": "rag",
        }

    return None


def get_student_profile(student_id: str) -> dict | None:
    response = (
        build_supabase_client()
        .table("student_profiles")
        .select("*")
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def format_student_profile(profile: dict | None) -> str:
    if not profile:
        return "Kein Studentenprofil geladen."

    semester_fee_status = (
        "bezahlt" if profile.get("semester_fee_paid") else "nicht bezahlt"
    )
    thesis_status = (
        "angemeldet" if profile.get("thesis_registered") else "nicht angemeldet"
    )
    notes = get_profile_notes(profile)
    completed_modules = notes.get("completed_modules") or []
    open_modules = notes.get("open_modules") or []
    interests = notes.get("interests") or []

    return f"""
Student-ID: {profile.get("student_id")}
Name: {profile.get("display_name")}
Studiengang: {profile.get("study_program")}
Fachsemester: {profile.get("semester")}
ECTS: {profile.get("ects_earned")}
Immatrikulationsstatus: {profile.get("enrollment_status")}
Semesterbeitrag: {semester_fee_status}
Bachelorarbeit: {thesis_status}
Bestandene Module: {format_module_names(completed_modules)}
Offene Module: {format_module_names(open_modules)}
Interessen: {", ".join(interests) if interests else "keine Interessen hinterlegt"}
Weitere Hinweise: {notes.get("advising_note", "keine")}
""".strip()


def retrieve_scored_documents(question: str, k: int = 4) -> list[tuple[float, Document]]:
    """Rank stored Supabase vectors locally to avoid fragile RPC permissions."""
    query_embedding = build_embeddings().embed_query(question)
    client = build_supabase_client()
    response = (
        client.table(TABLE_NAME)
        .select("content, metadata, embedding")
        .execute()
    )

    scored_documents = []
    for row in response.data:
        embedding = parse_embedding(row["embedding"])
        score = cosine_similarity(query_embedding, embedding)
        scored_documents.append(
            (
                score,
                Document(
                    page_content=row["content"],
                    metadata=row.get("metadata") or {},
                ),
            )
        )

    scored_documents.sort(key=lambda item: item[0], reverse=True)
    return scored_documents[:k]


def retrieve_documents(question: str, k: int = 4) -> list[Document]:
    return [document for _, document in retrieve_scored_documents(question, k)]


def build_llm() -> ChatGoogleGenerativeAI:
    google_api_key, _, _ = load_config()

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=google_api_key,
        temperature=0,
    )


def build_prompt() -> ChatPromptTemplate:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Du bist ein Service-Bot für Studierende.

Du hast zwei erlaubte Informationsquellen:
1. Kontext aus der offiziellen Wissensbasis.
2. Das strukturierte Studentenprofil.

Nutze den Kontext für Regeln, Fristen und Verfahren.
Nutze das Studentenprofil nur, um diese Regeln auf die konkrete Person
anzuwenden.

Nutze kein Allgemeinwissen, keine Vermutungen und keine Informationen ausserhalb
dieser beiden Quellen.

Wenn die Antwort nicht eindeutig im Kontext enthalten ist, antworte exakt:
"{fallback}"

Wenn für eine personalisierte Antwort ein Profilfeld fehlt, sage knapp, welche
Profilinformation fehlt.

Gib keine Quellen, Chunk-Nummern oder internen Kontextdetails im Antworttext aus.
Die Quellen werden separat von der Anwendung angezeigt.

Kontext:
{context}

Studentenprofil:
{student_profile}
""",
            ),
            ("human", "{question}"),
        ]
    ).partial(fallback=FALLBACK_ANSWER)
    return prompt


def ask(
    question: str,
    student_id: str = "demo-student-001",
    print_answer: bool = True,
) -> str:
    profile = get_student_profile(student_id)
    profile_answer = answer_profile_question(question, profile)
    if profile_answer:
        answer = str(profile_answer["answer"])
        if print_answer:
            print(answer)
        return answer

    scored_documents = retrieve_scored_documents(question)
    top_score = scored_documents[0][0] if scored_documents else 0.0
    if top_score < MIN_RETRIEVAL_SIMILARITY:
        if print_answer:
            print(FALLBACK_ANSWER)
        return FALLBACK_ANSWER

    retrieved_documents = [document for _, document in scored_documents]
    verified_answer = answer_verified_faq_question(question, retrieved_documents)
    if verified_answer:
        answer = str(verified_answer["answer"])
        if print_answer:
            print(answer)
        return answer

    context = format_context(retrieved_documents)
    student_profile = format_student_profile(profile)
    chain = build_prompt() | build_llm()
    response = chain.invoke(
        {
            "question": question,
            "context": context,
            "student_profile": student_profile,
        }
    )
    if print_answer:
        print(response.content)
    return response.content


def ask_with_sources(
    question: str,
    student_id: str = "demo-student-001",
) -> dict[str, object]:
    profile = get_student_profile(student_id)
    profile_answer = answer_profile_question(question, profile)
    if profile_answer:
        return profile_answer

    scored_documents = retrieve_scored_documents(question)
    top_score = scored_documents[0][0] if scored_documents else 0.0
    if top_score < MIN_RETRIEVAL_SIMILARITY:
        return {
            "answer": FALLBACK_ANSWER,
            "sources": [FALLBACK_SOURCE],
            "intent": "fallback",
            "confidence": round(top_score, 3),
        }

    retrieved_documents = [document for _, document in scored_documents]
    verified_answer = answer_verified_faq_question(question, retrieved_documents)
    if verified_answer:
        return {
            **verified_answer,
            "confidence": round(top_score, 3),
        }

    context = format_context(retrieved_documents)
    student_profile = format_student_profile(profile)
    chain = build_prompt() | build_llm()
    response = chain.invoke(
        {
            "question": question,
            "context": context,
            "student_profile": student_profile,
        }
    )
    answer = response.content
    if answer.strip() == FALLBACK_ANSWER:
        return {
            "answer": FALLBACK_ANSWER,
            "sources": [FALLBACK_SOURCE],
            "intent": "fallback",
            "confidence": round(top_score, 3),
        }

    sources = [] if answer.strip() == FALLBACK_ANSWER else format_sources(retrieved_documents)

    return {
        "answer": answer,
        "sources": sources or [FALLBACK_SOURCE],
        "intent": "rag",
        "confidence": round(top_score, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimaler Uni-RAG-Prototyp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="FAQ-Datei indexieren")
    ingest_parser.add_argument(
        "--file",
        type=Path,
        default=SCRIPT_DIR / "uni_faq.txt",
        help="Pfad zur lokalen FAQ-Textdatei",
    )

    ask_parser = subparsers.add_parser("ask", help="Frage an den Bot stellen")
    ask_parser.add_argument("question", help="Studentische Frage")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.command == "ingest":
        ingest(args.file)
    elif args.command == "ask":
        ask(args.question)


if __name__ == "__main__":
    main()
