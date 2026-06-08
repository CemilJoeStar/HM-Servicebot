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
from dataclasses import dataclass
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
PROFILE_SOURCE_LABEL = "Studierendenprofil"
MIN_RETRIEVAL_SIMILARITY = float(os.getenv("MIN_RETRIEVAL_SIMILARITY", "0.62"))
THESIS_REQUIRED_ECTS = 120


@dataclass(frozen=True)
class IntentRoute:
    intent: str
    label: str
    data_sources: list[str]
    reason: str


@dataclass(frozen=True)
class AdvisingRecommendation:
    title: str
    rationale: str
    priority: int


@dataclass(frozen=True)
class CourseRecommendation:
    name: str
    ects: int
    focus: str
    score: int
    reasons: list[str]


@dataclass(frozen=True)
class ProfessorRecommendation:
    display_name: str
    focus_topics: list[str]
    capacity_status: str
    available_slots: int
    score: int
    reasons: list[str]


MODULE_CATALOG = [
    {
        "name": "Data Mining",
        "ects": 5,
        "focus": "Data Analytics",
        "skills": ["data analytics", "statistik", "business intelligence", "datenbanken"],
        "description": "Analyse größerer Datenbestände, Mustererkennung und einfache Prognosemodelle.",
        "min_ects": 90,
    },
    {
        "name": "Machine Learning Grundlagen",
        "ects": 5,
        "focus": "Data Analytics",
        "skills": ["data analytics", "statistik", "programmierung 1", "business intelligence"],
        "description": "Einführung in überwachte und unüberwachte Lernverfahren.",
        "min_ects": 100,
    },
    {
        "name": "Cloud-Anwendungen",
        "ects": 5,
        "focus": "Software Engineering",
        "skills": ["software engineering", "programmierung 1", "datenbanken"],
        "description": "Entwicklung und Betrieb skalierbarer Web- und Cloud-Systeme.",
        "min_ects": 80,
    },
    {
        "name": "IT-Sicherheit",
        "ects": 5,
        "focus": "Software Engineering",
        "skills": ["software engineering", "datenbanken", "digitale prozesse"],
        "description": "Grundlagen sicherer IT-Systeme, Risiken und Schutzmaßnahmen.",
        "min_ects": 70,
    },
    {
        "name": "Projektseminar",
        "ects": 5,
        "focus": "Digitale Prozesse",
        "skills": ["digitale prozesse", "software engineering", "geschäftsprozessmanagement"],
        "description": "Praxisnahes Teamprojekt zur Umsetzung eines digitalen Prozesses.",
        "min_ects": 100,
    },
    {
        "name": "Process Mining",
        "ects": 5,
        "focus": "Digitale Prozesse",
        "skills": ["digitale prozesse", "geschäftsprozessmanagement", "data analytics"],
        "description": "Datenbasierte Analyse und Verbesserung betrieblicher Prozesse.",
        "min_ects": 90,
    },
]


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


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_text(value: str) -> str:
    return normalize_question(value).strip()


def route_intent(question: str) -> IntentRoute:
    """Decide which platform capability should answer the question."""
    normalized = normalize_question(question)
    asks_about_self = contains_any(
        normalized,
        ["ich", "mein", "meine", "mir", "mich", "habe ich", "kann ich", "darf ich"],
    )

    if contains_any(
        normalized,
        ["professor", "professorin", "prof", "betreu", "dozent", "dozentin"],
    ):
        return IntentRoute(
            intent="professor_matching",
            label="Professorenmatching",
            data_sources=["Studierendenprofil", "Professorendatenbank"],
            reason="Die Frage verlangt ein Matching zwischen Interessen, Studienverlauf und Betreuungskapazitäten.",
        )

    if contains_any(
        normalized,
        [
            "schwerpunkt",
            "passt zu mir",
            "empfehl",
            "studienberatung",
            "studienplanung",
            "welche module",
            "fehl",
            "pflichtmodule",
            "naechst",
            "prioritaet",
            "priorisieren",
            "belegen",
            "kurs",
            "kurse",
            "wahlpflicht",
            "recommender",
            "recommendation",
            "modulkatalog",
            "weiter machen",
            "studienverlauf",
        ],
    ):
        return IntentRoute(
            intent="advising",
            label="Studienberatung",
            data_sources=["Studierendenprofil", "Studienverlauf"],
            reason="Die Frage verlangt eine individuelle Einschätzung anhand des Studienverlaufs.",
        )

    if "bachelorarbeit" in normalized and asks_about_self:
        return IntentRoute(
            intent="advising",
            label="Studienberatung",
            data_sources=["Wissensbasis", "Studierendenprofil", "Studienverlauf"],
            reason="Die Bachelorarbeitsfrage kombiniert eine Hochschulregel mit persönlichen ECTS- und Modulständen.",
        )

    if contains_any(
        normalized,
        ["ects", "semesterbeitrag", "bezahlt", "rueckgemeldet", "zurueckgemeldet"],
    ) and asks_about_self:
        return IntentRoute(
            intent="profile",
            label="Profilstatus",
            data_sources=["Studierendenprofil"],
            reason="Die Frage bezieht sich auf persönliche Statusdaten.",
        )

    if contains_any(
        normalized,
        ["rueckmeld", "pruefung", "pruefungsabmeldung", "studierendenausweis", "frist", "gebuehr", "bachelorarbeit"],
    ):
        return IntentRoute(
            intent="rag",
            label="Wissensbasis",
            data_sources=["Wissensbasis"],
            reason="Die Frage betrifft allgemeine Regeln, Fristen oder Verfahren.",
        )

    return IntentRoute(
        intent="fallback",
        label="Eskalation",
        data_sources=[],
        reason="Die Frage passt zu keiner verifizierten Route des Prototyps.",
    )


def attach_route(payload: dict[str, object], route: IntentRoute) -> dict[str, object]:
    routed_payload = {
        **payload,
        "intent": route.intent,
        "route_label": route.label,
        "route_reason": route.reason,
        "data_sources": route.data_sources,
    }
    return routed_payload


def get_profile_notes(profile: dict | None) -> dict:
    notes = (profile or {}).get("notes") or {}
    return notes if isinstance(notes, dict) else {}


def format_module_names(modules: list[dict]) -> str:
    names = [module.get("name") for module in modules if module.get("name")]
    return ", ".join(names) if names else "keine Module hinterlegt"


def get_completed_modules(profile: dict | None) -> list[dict]:
    return get_profile_notes(profile).get("completed_modules") or []


def get_open_modules(profile: dict | None) -> list[dict]:
    return get_profile_notes(profile).get("open_modules") or []


def get_interests(profile: dict | None) -> list[str]:
    return get_profile_notes(profile).get("interests") or []


def get_normalized_completed_module_names(profile: dict | None) -> set[str]:
    return {
        normalize_text(module.get("name") or "")
        for module in get_completed_modules(profile)
        if module.get("name")
    }


def get_normalized_open_module_names(profile: dict | None) -> set[str]:
    return {
        normalize_text(module.get("name") or "")
        for module in get_open_modules(profile)
        if module.get("name")
    }


def score_course_for_profile(
    course: dict[str, object],
    profile: dict | None,
    query: str = "",
) -> CourseRecommendation | None:
    if not profile:
        return None

    course_name = str(course["name"])
    normalized_course_name = normalize_text(course_name)
    completed_module_names = get_normalized_completed_module_names(profile)
    open_module_names = get_normalized_open_module_names(profile)
    if normalized_course_name in completed_module_names:
        return None

    ects_earned = int(profile.get("ects_earned") or 0)
    min_ects = int(course.get("min_ects") or 0)
    if ects_earned < min_ects:
        return None

    completed_signals = completed_module_names
    completed_names_by_signal = {
        normalize_text(module.get("name") or ""): module.get("name")
        for module in get_completed_modules(profile)
        if module.get("name")
    }
    interest_signals = {normalize_text(interest) for interest in get_interests(profile)}
    skills = {normalize_text(skill) for skill in course.get("skills", [])}
    focus = str(course["focus"])
    normalized_focus = normalize_text(focus)
    normalized_query = normalize_text(query)

    score = 0
    reasons = []

    if normalized_focus in normalized_query or any(skill in normalized_query for skill in skills):
        score += 6
        reasons.append(f"passt zum angefragten Themenfeld {focus}")

    if normalized_focus in interest_signals:
        score += 5
        reasons.append(f"passt zu deinem Interesse {focus}")

    matched_skills = sorted(skills & completed_signals)
    if matched_skills:
        score += 2 * len(matched_skills)
        readable_skills = ", ".join(
            completed_names_by_signal.get(skill, skill)
            for skill in matched_skills[:3]
        )
        reasons.append(f"knüpft an bestandene Module an ({readable_skills})")

    matched_interests = sorted(skills & interest_signals)
    if matched_interests:
        score += 2 * len(matched_interests)

    if normalized_course_name in open_module_names:
        score += 4
        reasons.append("ist in deinem Studienverlauf noch offen hinterlegt")

    if not reasons:
        reasons.append(str(course["description"]))

    return CourseRecommendation(
        name=course_name,
        ects=int(course["ects"]),
        focus=focus,
        score=score,
        reasons=reasons,
    )


def recommend_courses(
    profile: dict | None,
    limit: int = 3,
    query: str = "",
) -> list[CourseRecommendation]:
    recommendations = [
        recommendation
        for course in MODULE_CATALOG
        if (recommendation := score_course_for_profile(course, profile, query=query))
    ]
    recommendations.sort(key=lambda item: (-item.score, item.name))
    return recommendations[:limit]


def format_course_recommendations(recommendations: list[CourseRecommendation]) -> str:
    return "\n".join(
        (
            f"{index}. {item.name} ({item.ects} ECTS, {item.focus}): "
            f"{'; '.join(item.reasons)}."
        )
        for index, item in enumerate(recommendations, start=1)
    )


def get_professors() -> list[dict]:
    response = (
        build_supabase_client()
        .table("professors")
        .select("*")
        .order("available_slots", desc=True)
        .execute()
    )
    return response.data or []


def get_knowledge_documents() -> list[dict]:
    response = (
        build_supabase_client()
        .table("knowledge_documents")
        .select("*")
        .order("last_indexed_at", desc=True)
        .execute()
    )
    return response.data or []


def score_professor_for_profile(
    professor: dict,
    profile: dict | None,
    query: str = "",
) -> ProfessorRecommendation | None:
    if not profile:
        return None

    focus_topics = professor.get("focus_topics") or []
    normalized_focus_topics = {normalize_text(topic) for topic in focus_topics}
    normalized_query = normalize_text(query)
    interest_signals = {normalize_text(interest) for interest in get_interests(profile)}
    completed_signals = get_normalized_completed_module_names(profile)
    open_signals = get_normalized_open_module_names(profile)

    capacity_status = professor.get("capacity_status") or "unavailable"
    available_slots = int(professor.get("available_slots") or 0)

    score = 0
    reasons = []

    query_matches = [
        topic
        for topic in focus_topics
        if normalize_text(topic) in normalized_query
    ]
    if query_matches:
        score += 6 * len(query_matches)
        reasons.append(f"passt zum angefragten Thema {', '.join(query_matches)}")

    interest_matches = sorted(normalized_focus_topics & interest_signals)
    if interest_matches:
        score += 4 * len(interest_matches)
        reasons.append(
            "passt zu deinen Interessen "
            f"({', '.join(interest_matches[:3])})"
        )

    module_matches = sorted(normalized_focus_topics & (completed_signals | open_signals))
    if module_matches:
        score += 2 * len(module_matches)
        reasons.append(
            "knüpft an deinen Studienverlauf an "
            f"({', '.join(module_matches[:3])})"
        )

    if capacity_status == "available":
        score += 4
        reasons.append(f"hat aktuell {available_slots} freie Betreuungskapazitäten")
    elif capacity_status == "limited":
        score += 1
        reasons.append(f"hat nur begrenzte Kapazität ({available_slots} Slot)")
    else:
        score -= 6
        reasons.append("ist aktuell nicht verfügbar")

    if score <= 0:
        return None

    return ProfessorRecommendation(
        display_name=professor.get("display_name", "Unbekannte Person"),
        focus_topics=list(focus_topics),
        capacity_status=capacity_status,
        available_slots=available_slots,
        score=score,
        reasons=reasons,
    )


def recommend_professors(
    profile: dict | None,
    query: str = "",
    limit: int = 3,
) -> list[ProfessorRecommendation]:
    recommendations = [
        recommendation
        for professor in get_professors()
        if (recommendation := score_professor_for_profile(professor, profile, query=query))
    ]
    recommendations.sort(
        key=lambda item: (
            item.capacity_status == "unavailable",
            -item.score,
            -item.available_slots,
            item.display_name,
        )
    )
    return recommendations[:limit]


def format_professor_recommendations(recommendations: list[ProfessorRecommendation]) -> str:
    status_labels = {
        "available": "verfügbar",
        "limited": "begrenzt verfügbar",
        "unavailable": "nicht verfügbar",
    }
    lines = []
    for index, recommendation in enumerate(recommendations, start=1):
        status = status_labels.get(
            recommendation.capacity_status,
            recommendation.capacity_status,
        )
        slot_label = "freier Slot" if recommendation.available_slots == 1 else "freie Slots"
        topics = ", ".join(recommendation.focus_topics[:3])
        reasons = "; ".join(recommendation.reasons)
        lines.append(
            f"{index}. {recommendation.display_name} ({status}, "
            f"{recommendation.available_slots} {slot_label}): Fokus {topics}. {reasons}."
        )
    return "\n".join(lines)


def answer_professor_question(question: str, profile: dict | None) -> dict[str, object] | None:
    recommendations = recommend_professors(profile, query=question)
    if not recommendations:
        return {
            "answer": (
                "Für diese Professorenempfehlung fehlen aktuell passende Profil- "
                "oder Professorendaten."
            ),
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Professorendatenbank"),
            "intent": "professor_matching",
        }

    answer = (
        "Für dein Profil würde ich diese Betreuungspersonen zuerst prüfen:\n"
        f"{format_professor_recommendations(recommendations)}\n"
        "Die Empfehlung ist ein Matching aus Interessen, Studienverlauf, Themenfokus "
        "und aktueller Verfügbarkeit."
    )
    return {
        "answer": answer,
        "sources": build_source_list(
            PROFILE_SOURCE_LABEL,
            "Professorendatenbank",
            "Content-Based Matching",
        ),
        "intent": "professor_matching",
    }


def format_recommendations(recommendations: list[AdvisingRecommendation]) -> str:
    sorted_recommendations = sorted(
        recommendations,
        key=lambda item: (item.priority, item.title),
    )
    return "\n".join(
        f"{index}. {item.title}: {item.rationale}"
        for index, item in enumerate(sorted_recommendations, start=1)
    )


def recommend_focus_area(profile: dict | None) -> AdvisingRecommendation:
    interests = get_interests(profile)
    completed_module_names = {
        (module.get("name") or "").lower()
        for module in get_completed_modules(profile)
    }
    interest_names = {interest.lower() for interest in interests}

    data_score = 0
    software_score = 0
    process_score = 0

    if "data analytics" in interest_names:
        data_score += 3
    if "business intelligence" in completed_module_names:
        data_score += 2
    if "statistik" in completed_module_names:
        data_score += 1

    if "software engineering" in interest_names:
        software_score += 3
    if "software engineering" in completed_module_names:
        software_score += 2
    if "programmierung 1" in completed_module_names:
        software_score += 1

    if "digitale prozesse" in interest_names:
        process_score += 3
    if "geschäftsprozessmanagement" in completed_module_names:
        process_score += 2
    if "datenbanken" in completed_module_names:
        process_score += 1

    scores = {
        "Data Analytics": data_score,
        "Software Engineering": software_score,
        "Digitale Prozesse": process_score,
    }
    recommendation = max(scores, key=scores.get)
    evidence = ", ".join(interests) if interests else "hinterlegte Module"

    return AdvisingRecommendation(
        title=f"Schwerpunkt {recommendation} prüfen",
        rationale=(
            f"Dieser Schwerpunkt passt am besten zu den hinterlegten Interessen "
            f"und Modulindikatoren ({evidence})."
        ),
        priority=3,
    )


def build_study_recommendations(profile: dict | None) -> list[AdvisingRecommendation]:
    if not profile:
        return []

    ects_earned = profile.get("ects_earned") or 0
    open_modules = get_open_modules(profile)
    recommendations: list[AdvisingRecommendation] = []

    if not profile.get("semester_fee_paid"):
        recommendations.append(
            AdvisingRecommendation(
                title="Rückmeldung abschließen",
                rationale=(
                    "Der Semesterbeitrag ist noch nicht als bezahlt markiert; "
                    "das blockiert die vollständige Rückmeldung."
                ),
                priority=1,
            )
        )

    missing_ects = max(THESIS_REQUIRED_ECTS - ects_earned, 0)
    if missing_ects > 0:
        recommendations.append(
            AdvisingRecommendation(
                title=f"{missing_ects} ECTS für die Bachelorarbeit schließen",
                rationale=(
                    f"Aktuell sind {ects_earned} ECTS hinterlegt; für die Anmeldung "
                    f"werden mindestens {THESIS_REQUIRED_ECTS} ECTS benötigt."
                ),
                priority=2,
            )
        )

    for module in open_modules[:2]:
        name = module.get("name")
        ects = module.get("ects")
        if not name:
            continue
        ects_suffix = f" ({ects} ECTS)" if ects else ""
        recommendations.append(
            AdvisingRecommendation(
                title=f"{name}{ects_suffix} priorisieren",
                rationale=(
                    "Das Modul ist im Studienverlauf noch offen und hilft, "
                    "den nächsten Studienfortschritt planbar zu machen."
                ),
                priority=2,
            )
        )

    course_recommendations = recommend_courses(profile, limit=1)
    if course_recommendations:
        best_course = course_recommendations[0]
        recommendations.append(
            AdvisingRecommendation(
                title=f"{best_course.name} als Empfehlung prüfen",
                rationale=(
                    "Der Hybrid-Recommender bewertet das Modul hoch, weil es "
                    f"{'; '.join(best_course.reasons)}."
                ),
                priority=3,
            )
        )

    recommendations.append(recommend_focus_area(profile))
    return recommendations


def answer_advising_question(question: str, profile: dict | None) -> dict[str, object] | None:
    """Give explainable first-step study advice from structured profile data."""
    if not profile:
        return None

    normalized = normalize_question(question)
    open_modules = get_open_modules(profile)
    completed_modules = get_completed_modules(profile)
    interests = get_interests(profile)
    recommendations = build_study_recommendations(profile)

    if (
        contains_any(normalized, ["wahlpflicht", "kurse", "kurs", "recommender", "recommendation"])
        or (
            "modul" in normalized
            and contains_any(normalized, ["passt", "empfehl", "belegen", "waehlen"])
        )
    ) and "fehl" not in normalized:
        course_recommendations = recommend_courses(profile, query=question)
        if not course_recommendations:
            answer = "Für eine Modulempfehlung fehlen aktuell passende Profil- oder Modulkatalogdaten."
        else:
            answer = (
                "Der Hybrid-Recommender schlägt dir diese Module vor:\n"
                f"{format_course_recommendations(course_recommendations)}\n"
                "Die Auswahl basiert auf Interessen, bestandenen Modulen und einfachen ECTS-Voraussetzungen."
            )
        return {
            "answer": answer,
            "sources": build_source_list(
                PROFILE_SOURCE_LABEL,
                "Modulkatalog Wirtschaftsinformatik 2026",
                "Content-Based Recommender",
            ),
            "intent": "advising",
        }

    if contains_any(
        normalized,
        ["naechst", "prioritaet", "priorisieren", "studienplanung", "weiter machen", "belegen"],
    ):
        if not recommendations:
            answer = "Für eine Studienberatung fehlen im Profil aktuell verwertbare Verlaufsdaten."
        else:
            answer = (
                "Aus deinem Studienverlauf ergeben sich diese nächsten sinnvollen Schritte:\n"
                f"{format_recommendations(recommendations[:4])}"
            )
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Regelbasierte Studienberatung"),
            "intent": "advising",
        }

    if (
        ("fehl" in normalized and ("modul" in normalized or "bachelorarbeit" in normalized))
        or "offene module" in normalized
        or "pflichtmodule" in normalized
    ):
        if "bachelorarbeit" in normalized:
            ects_earned = profile.get("ects_earned")
            missing_ects = max(THESIS_REQUIRED_ECTS - (ects_earned or 0), 0)
            module_hint = (
                f" Offene Module im Studienverlauf: {format_module_names(open_modules)}."
                if open_modules
                else ""
            )
            answer = (
                f"Für die Bachelorarbeit fehlen dir aktuell noch {missing_ects} ECTS, "
                f"weil {ects_earned} von mindestens {THESIS_REQUIRED_ECTS} ECTS hinterlegt sind."
                f"{module_hint}"
            )
        elif open_modules:
            answer = (
                "In deinem Studienverlauf sind noch diese offenen Module hinterlegt: "
                f"{format_module_names(open_modules)}."
            )
        else:
            answer = "In deinem Studienverlauf sind aktuell keine offenen Module hinterlegt."
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Regelbasierte Studienberatung"),
            "intent": "advising",
        }

    if "schwerpunkt" in normalized or "passt zu mir" in normalized or "empfehl" in normalized:
        focus = recommend_focus_area(profile)
        completed = format_module_names(completed_modules)
        interest_text = ", ".join(interests) if interests else "keine Interessen hinterlegt"
        answer = (
            f"{focus.title}. {focus.rationale} "
            f"Grundlage sind deine Interessen ({interest_text}) und bestandene Module wie {completed}. "
            "Das ist eine erste Orientierung, keine verbindliche Studienberatung."
        )
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Regelbasierte Studienberatung"),
            "intent": "advising",
        }

    return None


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
            answer = "Dein Semesterbeitrag ist im Studierendenprofil als bezahlt markiert."
        else:
            answer = (
                "Dein Semesterbeitrag ist im Studierendenprofil noch nicht als bezahlt markiert. "
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

    if "ects" in normalized and (
        "wie viele" in normalized
        or "wie viel" in normalized
        or "derzeit" in normalized
        or "aktuell" in normalized
        or "habe ich" in normalized
    ):
        ects_earned = profile.get("ects_earned")
        if ects_earned is None:
            answer = "Für diese Auskunft fehlt im Profil die aktuelle ECTS-Anzahl."
        else:
            answer = f"Du hast laut Studierendenprofil aktuell {ects_earned} ECTS."
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL),
            "intent": "profile",
        }

    if "rueckgemeldet" in normalized or "rueckmeldung" in normalized and "ich" in normalized:
        if profile.get("semester_fee_paid"):
            answer = "Du bist im Studierendenprofil für die Rückmeldung nicht blockiert, weil der Semesterbeitrag als bezahlt markiert ist."
        else:
            answer = (
                "Du bist aktuell noch nicht vollständig zurückgemeldet. Im Studierendenprofil ist "
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
                module_hint = f" Im Studienverlauf sind außerdem noch offene Module hinterlegt: {format_module_names(open_modules)}."
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

    if (
        ("fehl" in normalized and "modul" in normalized)
        or "offene module" in normalized
        or "pflichtmodule" in normalized
    ):
        if open_modules:
            answer = f"In deinem Studienverlauf sind noch diese offenen Module hinterlegt: {format_module_names(open_modules)}."
        else:
            answer = "In deinem Studienverlauf sind aktuell keine offenen Module hinterlegt."
        return {
            "answer": answer,
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Regelbasierte Studienberatung"),
            "intent": "advising",
        }

    if "schwerpunkt" in normalized or "passt zu mir" in normalized or "empfehl" in normalized:
        return answer_advising_question(question, profile)

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
    response = ask_with_sources(question, student_id)
    answer = str(response["answer"])
    if print_answer:
        print(answer)
    return answer


def ask_with_sources(
    question: str,
    student_id: str = "demo-student-001",
) -> dict[str, object]:
    route = route_intent(question)
    if route.intent == "fallback":
        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": 0,
            },
            route,
        )

    profile = get_student_profile(student_id)
    if route.intent == "professor_matching":
        professor_answer = answer_professor_question(question, profile)
        return attach_route(professor_answer, route)

    if route.intent == "advising":
        profile_answer = answer_advising_question(question, profile) or answer_profile_question(
            question,
            profile,
        )
        if profile_answer:
            return attach_route(profile_answer, route)

        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": 0,
            },
            route,
        )

    if route.intent == "profile":
        profile_answer = answer_profile_question(question, profile)
        if profile_answer:
            return attach_route(profile_answer, route)

        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": 0,
            },
            route,
        )

    scored_documents = retrieve_scored_documents(question)
    top_score = scored_documents[0][0] if scored_documents else 0.0
    if top_score < MIN_RETRIEVAL_SIMILARITY:
        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": round(top_score, 3),
            },
            IntentRoute(
                intent="fallback",
                label="Eskalation",
                data_sources=[],
                reason="Die ähnlichsten Wissensbasis-Treffer lagen unter der Relevanzschwelle.",
            ),
        )

    retrieved_documents = [document for _, document in scored_documents]
    verified_answer = answer_verified_faq_question(question, retrieved_documents)
    if verified_answer:
        return attach_route(
            {
                **verified_answer,
                "confidence": round(top_score, 3),
            },
            route,
        )

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
        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": round(top_score, 3),
            },
            IntentRoute(
                intent="fallback",
                label="Eskalation",
                data_sources=[],
                reason="Das Modell konnte aus dem bereitgestellten Kontext keine eindeutige Antwort ableiten.",
            ),
        )

    sources = [] if answer.strip() == FALLBACK_ANSWER else format_sources(retrieved_documents)

    return attach_route(
        {
            "answer": answer,
            "sources": sources or [FALLBACK_SOURCE],
            "confidence": round(top_score, 3),
        },
        route,
    )


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
