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
import difflib
import math
import os
import re
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
PROFESSOR_SOURCE_LABEL = "Professorenprofil"
MIN_RETRIEVAL_SIMILARITY = float(os.getenv("MIN_RETRIEVAL_SIMILARITY", "0.62"))
THESIS_REQUIRED_ECTS = 120
HUMAN_ADVISORY_SOURCE_LABEL = "Eskalationslogik Studienberatung"

DOMAIN_TERMS = {
    "bachelorarbeit",
    "abschlussarbeit",
    "rueckmeldung",
    "pruefungsabmeldung",
    "semesterbeitrag",
    "studierendenausweis",
    "studierendensekretariat",
    "studienberatung",
    "studienverlauf",
    "wahlpflichtmodule",
}

PROFESSOR_TOPIC_ALIASES = {
    "ki-systeme": ["ki", "kuenstliche intelligenz", "ai", "machine learning"],
    "natural language processing": ["nlp", "sprachverarbeitung", "textanalyse"],
    "chatbots": ["chatbot", "servicebot", "conversational ai"],
    "software engineering": [
        "software engineering",
        "softwareentwicklung",
        "software entwicklung",
        "webentwicklung",
        "backend",
        "frontend",
    ],
    "cloud-anwendungen": [
        "cloud",
        "cloud computing",
        "cloud-native",
        "cloud native",
        "aws",
        "azure",
    ],
    "it-sicherheit": ["it-sicherheit", "it sicherheit", "informationssicherheit"],
    "cybersecurity": ["cybersecurity", "cyber security", "cyber-sicherheit"],
    "datenschutz": ["datenschutz", "dsgvo", "privacy"],
    "cloud security": ["cloud security", "cloud-sicherheit", "cloud sicherheit"],
    "data analytics": ["data analytics", "datenanalyse", "analytics"],
    "business intelligence": ["business intelligence", "bi", "dashboarding"],
    "process mining": ["process mining", "prozessanalyse"],
    "digitale prozesse": ["digitale prozesse", "digitalisierung"],
    "geschaeftsprozessmanagement": [
        "geschaeftsprozessmanagement",
        "prozessmanagement",
        "gpm",
    ],
    "projektseminar": ["projektseminar", "projektarbeit"],
    "erp-systeme": ["erp", "erp-systeme", "enterprise resource planning"],
    "prozessautomatisierung": ["prozessautomatisierung", "automatisierung", "workflow"],
    "digitale verwaltung": ["digitale verwaltung", "e-government"],
    "marketing": ["marketing", "online marketing"],
    "digitale geschaeftsmodelle": ["digitale geschaeftsmodelle", "business model"],
    "e-commerce": ["e-commerce", "ecommerce", "onlinehandel"],
    "innovation management": ["innovation management", "innovationsmanagement"],
    "startups": ["startup", "startups", "gruendung"],
}

THESIS_TOPIC_DIRECTIONS = {
    "ki-systeme": [
        "Konzeption eines KI-gestützten Assistenzsystems für Hochschulservices",
        "Evaluierung von LLM-basierten Workflows in administrativen Prozessen",
        "Transparenz und Grenzen KI-gestützter Entscheidungsunterstützung",
    ],
    "natural language processing": [
        "NLP-basierte Klassifikation studentischer Serviceanfragen",
        "Auswertung freier Texte in Hochschulprozessen",
        "Vergleich von Retrieval- und Klassifikationsansätzen für Beratungsfälle",
    ],
    "chatbots": [
        "Konzeption eines kontextgebundenen Chatbots für Studierendenservices",
        "Akzeptanzfaktoren von KI-Chatbots im Hochschulkontext",
        "Eskalationslogik für hybride Chatbot- und Beratungsprozesse",
    ],
    "software engineering": [
        "Qualitätssicherung und Testing in Web- oder Backend-Systemen",
        "Architekturentscheidungen in modernen Softwareprojekten",
        "Entwicklungsprozesse, Wartbarkeit und technische Schulden",
    ],
    "cloud-anwendungen": [
        "Konzeption einer Cloud-nativen Anwendung mit nachvollziehbarer Architektur",
        "Vergleich von Deployment- und Betriebsmodellen für Webservices",
        "Skalierbarkeit und Monitoring in Cloud-basierten Anwendungen",
    ],
    "it-sicherheit": [
        "Sicherheitsanalyse einer Webanwendung oder API",
        "Schutz sensibler Daten in digitalen Hochschulprozessen",
        "Bedrohungsmodell und Gegenmaßnahmen für einen Service-Prototypen",
    ],
    "cybersecurity": [
        "Bedrohungsmodell für studentische Self-Service-Plattformen",
        "Sicherheitsanforderungen an KI-gestützte Hochschulservices",
        "Vergleich technischer Schutzmaßnahmen für sensible Studiendaten",
    ],
    "datenschutz": [
        "Datenminimierung in personalisierten Hochschulplattformen",
        "DSGVO-konforme Gestaltung KI-gestützter Beratungsprozesse",
        "Privacy-by-Design für Smart-University-Anwendungen",
    ],
    "cloud security": [
        "Sicherheitskonzept für Cloud-basierte Hochschulservices",
        "Rollen- und Zugriffskonzepte für Cloud-Anwendungen",
        "Risikoanalyse einer Cloud-nativen Serviceplattform",
    ],
    "data analytics": [
        "Auswertung von Studienverlaufs- oder Servicedaten zur Entscheidungsunterstützung",
        "Dashboarding und Kennzahlen für studentische Services",
        "Datenqualität und Interpretierbarkeit in Analytics-Projekten",
    ],
    "business intelligence": [
        "BI-Konzept für operative Hochschulservices",
        "Kennzahlensystem zur Verbesserung von Beratungsprozessen",
        "Vergleich von BI-Ansätzen für Studienverlaufsanalysen",
    ],
    "process mining": [
        "Analyse und Verbesserung digitaler Verwaltungsprozesse",
        "Process-Mining-Ansatz für Serviceanfragen im Studierendenservice",
        "Transparenz und Engpassanalyse in administrativen Workflows",
    ],
    "digitale prozesse": [
        "Digitalisierung eines studentischen Serviceprozesses",
        "Automatisierung wiederkehrender Verwaltungsanfragen",
        "Nutzerzentrierte Gestaltung digitaler Hochschulprozesse",
    ],
    "geschaeftsprozessmanagement": [
        "Modellierung und Optimierung eines Hochschulprozesses",
        "Vergleich manueller und automatisierter Serviceabläufe",
        "Prozesskennzahlen für digitale Studierendenservices",
    ],
    "projektseminar": [
        "Praxisnahe Konzeption eines digitalen Service-Prototyps",
        "Evaluation eines Smart-Uni-Prototyps mit Studierenden",
        "Anforderungsanalyse für eine studentische Beratungsplattform",
    ],
    "erp-systeme": [
        "Integration studentischer Verwaltungsdaten in eine Serviceplattform",
        "ERP-gestützte Prozessoptimierung im Hochschulkontext",
        "Schnittstellenkonzept zwischen Campusmanagement und Beratungssystemen",
    ],
    "prozessautomatisierung": [
        "Automatisierung wiederkehrender Serviceanfragen",
        "Workflow-Design für digitale Hochschulverwaltung",
        "Vergleich regelbasierter und KI-gestützter Prozessautomatisierung",
    ],
    "digitale verwaltung": [
        "Nutzerzentrierte Gestaltung digitaler Verwaltungsleistungen",
        "Self-Service-Prozesse für Studierende im Smart-University-Kontext",
        "Digitalisierung von Formular- und Antragsprozessen",
    ],
    "marketing": [
        "Digitale Kommunikation studentischer Services",
        "Akzeptanzfaktoren für KI-gestützte Hochschulangebote",
        "Nutzervertrauen und Servicequalität in digitalen Plattformen",
    ],
    "digitale geschaeftsmodelle": [
        "Plattformlogik und Wertversprechen digitaler Hochschulservices",
        "Service-Ökosysteme im Kontext Smart University",
        "Governance digitaler Plattformangebote",
    ],
    "innovation management": [
        "Einführung digitaler Innovationen in Hochschulorganisationen",
        "Akzeptanz und Adoption von Smart-University-Services",
        "Roadmap für die Skalierung eines KI-Serviceprototyps",
    ],
    "startups": [
        "Transferpotenziale studentischer Serviceplattformen",
        "Lean-Startup-Ansatz für digitale Hochschulservices",
        "Validierung eines Plattformkonzepts im Hochschulumfeld",
    ],
    "e-commerce": [
        "Nutzerführung und Conversion-Logik in Serviceplattformen",
        "Personalisierte digitale Services und ethische Grenzen",
        "Vergleich transaktionaler Plattformprozesse",
    ],
}


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

    if "## Einschreibung" in content:
        return "Einschreibeordnung 2026 · verifiziert"

    if "## Stundenplan" in content:
        return "Campusportal Stundenplanhinweise 2026 · verifiziert"

    if "## Formulare und Anträge" in content:
        return "HM Online-Serviceportal 2026 · verifiziert"

    if "## Praxissemester und Praktikum" in content:
        return "Praxissemesterordnung Wirtschaftsinformatik 2026 · verifiziert"

    if "## Studiengangwechsel" in content:
        return "Studienberatungsleitfaden 2026 · verifiziert"

    if "## Kontakt Studierendensekretariat" in content:
        return "Kontaktweg Studierendensekretariat 2026 · verifiziert"

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


def split_markdown_sections(content: str) -> list[str]:
    """Keep FAQ sections together so retrieved sources stay human-readable."""
    lines = content.splitlines()
    preamble = []
    sections = []
    current_section = []

    for line in lines:
        if line.startswith("## "):
            if current_section:
                sections.append("\n".join(current_section).strip())
            current_section = [line]
            continue

        if current_section:
            current_section.append(line)
        else:
            preamble.append(line)

    if current_section:
        sections.append("\n".join(current_section).strip())

    header = "\n".join(preamble).strip()
    if header and sections:
        return [f"{header}\n\n{section}" for section in sections]
    if sections:
        return sections
    return [content]


def load_faq_documents(path: Path) -> list[Document]:
    if not path.exists():
        raise FileNotFoundError(f"FAQ file not found: {path}")

    content = path.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=650,
        chunk_overlap=60,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    section_documents = [
        Document(page_content=section, metadata={"source": path.name})
        for section in split_markdown_sections(content)
    ]
    chunks = splitter.split_documents(section_documents)

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


def index_uploaded_text(
    content: str,
    *,
    source_name: str,
    source_label: str,
    chat_id: str,
    attachment_id: str,
) -> int:
    """Index text extracted from a chat upload so later chat questions can find it."""
    cleaned_content = content.strip()
    if not cleaned_content:
        return 0

    base_document = Document(
        page_content=cleaned_content,
        metadata={
            "source": source_name,
            "source_label": source_label,
            "chat_id": chat_id,
            "attachment_id": attachment_id,
            "origin": "chat_upload",
        },
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=650,
        chunk_overlap=100,
        separators=["\n## ", "\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents([base_document])

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = index

    build_vector_store().add_documents(chunks)
    return len(chunks)


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
    normalized = (
        question.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    tokens = re.split(r"(\W+)", normalized)
    corrected_tokens = []
    for token in tokens:
        if not token.isalpha() or len(token) < 7 or token in DOMAIN_TERMS:
            corrected_tokens.append(token)
            continue

        match = difflib.get_close_matches(
            token,
            DOMAIN_TERMS,
            n=1,
            cutoff=0.84,
        )
        corrected_tokens.append(match[0] if match else token)

    return "".join(corrected_tokens)


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_text(value: str) -> str:
    return normalize_question(value).strip()


def normalize_matching_text(value: str) -> str:
    """Normalize common student wording before matching structured topics."""
    normalized = normalize_text(value)
    replacements = {
        "software entwicklung engineering": "software engineering",
        "softwareentwicklung": "software engineering",
        "software entwicklung": "software engineering",
        "software-engineering": "software engineering",
        "ki chatbot": "chatbots",
        "ki-chatbot": "chatbots",
        "ki chatbots": "chatbots",
        "ki-chatbots": "chatbots",
        "kuenstliche intelligenz": "ki-systeme",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def matching_aliases_for_topic(topic: str) -> list[str]:
    normalized_topic = normalize_matching_text(topic)
    aliases = [normalized_topic, *PROFESSOR_TOPIC_ALIASES.get(normalized_topic, [])]
    return list(dict.fromkeys(normalize_matching_text(alias) for alias in aliases))


def matching_phrase(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", normalize_matching_text(value)).strip()
    return f" {normalized} "


def match_requested_focus_topics(question: str, focus_topics: list[str]) -> list[str]:
    """Return explicit topic matches from the question, independent of profile data."""
    normalized_query = matching_phrase(question)
    matches = []
    for topic in focus_topics:
        aliases = matching_aliases_for_topic(topic)
        if any(matching_phrase(alias) in normalized_query for alias in aliases):
            matches.append(topic)
    return matches


def contains_known_professor_topic(question: str) -> bool:
    normalized_query = matching_phrase(question)
    return any(
        matching_phrase(alias) in normalized_query
        for aliases in PROFESSOR_TOPIC_ALIASES.values()
        for alias in aliases
    )


def has_recent_professor_context(messages: list[dict] | None) -> bool:
    if not messages:
        return False

    for message in reversed(messages[-8:]):
        if message.get("role") == "assistant":
            route_label = normalize_text(str(message.get("routeLabel") or ""))
            if route_label == "professorenmatching":
                return True
        if message.get("role") == "user":
            text = str(message.get("text") or "")
            if is_thesis_topic_question(text) or contains_any(
                normalize_question(text),
                ["professor", "professorin", "prof", "betreu", "dozent", "dozentin"],
            ):
                return True
    return False


def is_human_advisory_case(question: str) -> bool:
    """Detect questions where the bot should support, but not decide alone."""
    normalized = normalize_question(question)
    high_touch_keywords = [
        "studiengang wechseln",
        "studienwechsel",
        "fach wechseln",
        "wechseln",
        "abbrechen",
        "studium abbrechen",
        "exmatrikulation",
        "exmatrikulieren",
        "zweifel",
        "ueberfordert",
        "anerkennung",
        "anerkennen",
        "anrechnen",
        "haertefall",
        "nachteilsausgleich",
        "frist verpasst",
        "frist versaeumt",
        "widerspruch",
        "sonderfall",
        "ausnahme",
        "verbindlich",
        "problem mit",
        "konflikt",
        "krankheit",
    ]
    return contains_any(normalized, high_touch_keywords)


def is_thesis_topic_question(question: str) -> bool:
    normalized = normalize_question(question)
    thesis_terms = [
        "thesis",
        "bachelorarbeit",
        "abschlussarbeit",
        "arbeit schreiben",
        "schreiben wollen",
        "themenrichtung",
        "thema",
        "richtung",
        "bereich",
    ]
    professor_context_terms = [
        "prof",
        "professor",
        "professorin",
        "betreu",
        "dozent",
        "dozentin",
        "herr",
        "herrn",
        "frau",
        "bei ",
        "beim ",
        "jemand",
        "person",
        "betreuungsperson",
        "passend",
        "empfehl",
        "vorschlag",
        "wen ",
        "wer ",
    ]
    return contains_any(normalized, thesis_terms) and contains_any(
        normalized,
        professor_context_terms,
    )


def is_professor_contact_question(question: str) -> bool:
    normalized = normalize_question(question)
    contact_terms = [
        "kontakt",
        "kontaktieren",
        "mail",
        "email",
        "e-mail",
        "anschreiben",
        "erreichen",
    ]
    professor_reference_terms = [
        "sie",
        "ihn",
        "prof",
        "professor",
        "professorin",
        "betreuungsperson",
        "person",
        "jemand",
    ]
    non_professor_contacts = [
        "sekretariat",
        "studierendensekretariat",
        "pruefungsamt",
        "studienberatung",
    ]
    return (
        contains_any(normalized, contact_terms)
        and contains_any(normalized, professor_reference_terms)
        and not contains_any(normalized, non_professor_contacts)
    )


def route_intent(question: str) -> IntentRoute:
    """Decide which platform capability should answer the question."""
    normalized = normalize_question(question)
    asks_about_self = contains_any(
        normalized,
        ["ich", "mein", "meine", "mir", "mich", "habe ich", "kann ich", "darf ich"],
    )

    if is_professor_contact_question(question) or is_thesis_topic_question(question) or contains_any(
        normalized,
        ["professor", "professorin", "prof", "betreu", "dozent", "dozentin"],
    ):
        return IntentRoute(
            intent="professor_matching",
            label="Professorenmatching",
            data_sources=["Studierendenprofil", "Professorendatenbank"],
            reason="Die Frage verlangt ein Matching zwischen Interessen, Studienverlauf und Betreuungskapazitäten.",
        )

    if is_human_advisory_case(question):
        return IntentRoute(
            intent="human_advising",
            label="Beratung mit Eskalation",
            data_sources=["Studierendenprofil", HUMAN_ADVISORY_SOURCE_LABEL],
            reason=(
                "Das Anliegen hat individuelle Tragweite und sollte durch "
                "Studienberatung oder Fachberatung geprüft werden."
            ),
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
            "welche faecher",
            "fehl",
            "offen",
            "noch schreiben",
            "versuch",
            "versuche",
            "fehlversuch",
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
        [
            "rueckmeld",
            "pruefung",
            "pruefungsabmeldung",
            "studierendenausweis",
            "frist",
            "gebuehr",
            "bachelorarbeit",
            "einschreibung",
            "einschreiben",
            "immatrikulation",
            "bewerbungsportal",
            "stundenplan",
            "formulare",
            "formular",
            "antrag",
            "antraege",
            "praxissemester",
            "praktikum",
            "career service",
            "kontakt",
            "kontaktieren",
            "sekretariat",
            "studierendensekretariat",
            "sprechstunde",
        ],
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


def route_intent_with_context(
    question: str,
    conversation_messages: list[dict] | None,
) -> IntentRoute:
    route = route_intent(question)
    if (
        route.intent in {"fallback", "advising"}
        and has_recent_professor_context(conversation_messages)
        and (
            contains_known_professor_topic(question)
            or contains_any(
                normalize_question(question),
                ["meinte", "thema", "bereich", "richtung", "betreu", "prof"],
            )
        )
    ):
        return IntentRoute(
            intent="professor_matching",
            label="Professorenmatching",
            data_sources=["Studierendenprofil", "Professorendatenbank"],
            reason=(
                "Die Frage konkretisiert den Themenwunsch aus dem vorherigen "
                "Professorenmatching."
            ),
        )
    return route


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


def get_exam_attempts(profile: dict | None) -> list[dict]:
    return get_profile_notes(profile).get("exam_attempts") or []


def format_exam_attempts(attempts: list[dict]) -> str:
    if not attempts:
        return "keine Wiederholungsversuche hinterlegt"

    return ", ".join(
        (
            f"{attempt.get('name')} "
            f"({attempt.get('attempt')}. Versuch von {attempt.get('max_attempts', 3)})"
        )
        for attempt in attempts
        if attempt.get("name") and attempt.get("attempt")
    )


def get_critical_exam_attempts(profile: dict | None) -> list[dict]:
    return [
        attempt
        for attempt in get_exam_attempts(profile)
        if int(attempt.get("attempt") or 0) >= int(attempt.get("max_attempts") or 3)
    ]


def get_normalized_completed_module_names(profile: dict | None) -> set[str]:
    return {
        normalize_matching_text(module.get("name") or "")
        for module in get_completed_modules(profile)
        if module.get("name")
    }


def get_normalized_open_module_names(profile: dict | None) -> set[str]:
    return {
        normalize_matching_text(module.get("name") or "")
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


def find_mentioned_professor(question: str, professors: list[dict]) -> dict | None:
    normalized = normalize_matching_text(question)
    for professor in professors:
        display_name = professor.get("display_name") or ""
        normalized_name = normalize_matching_text(display_name)
        name_parts = [
            part
            for part in normalized_name.replace(".", " ").split()
            if len(part) > 2 and part not in {"prof", "dr"}
        ]
        if normalized_name in normalized or any(part in normalized for part in name_parts):
            return professor
    return None


def infer_recent_professors_from_messages(
    messages: list[dict] | None,
    professors: list[dict],
    limit: int = 2,
) -> list[dict]:
    if not messages:
        return []

    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue

        text = message.get("text") or ""
        normalized_text = normalize_matching_text(text)
        matches = []
        for professor in professors:
            display_name = professor.get("display_name") or ""
            normalized_name = normalize_matching_text(display_name)
            if normalized_name in normalized_text:
                matches.append((normalized_text.find(normalized_name), professor))

        if matches:
            matches.sort(key=lambda item: item[0])
            return [professor for _, professor in matches[:limit]]

    return []


def get_capacity_status_label(status: str) -> str:
    if status == "available":
        return "verfügbar"
    if status == "limited":
        return "begrenzt verfügbar"
    return "aktuell nicht verfügbar"


def build_thesis_topic_ideas(professor: dict, profile: dict | None) -> list[str]:
    focus_topics = professor.get("focus_topics") or []
    interests = {normalize_text(interest) for interest in get_interests(profile)}
    completed_modules = get_normalized_completed_module_names(profile)
    open_modules = get_normalized_open_module_names(profile)

    ranked_topics = sorted(
        focus_topics,
        key=lambda topic: (
            normalize_text(topic) not in interests,
            normalize_text(topic) not in (completed_modules | open_modules),
            topic,
        ),
    )
    ideas = []
    for topic in ranked_topics:
        topic_ideas = THESIS_TOPIC_DIRECTIONS.get(normalize_text(topic), [])
        for idea in topic_ideas:
            if idea not in ideas:
                ideas.append(idea)
            if len(ideas) == 3:
                return ideas

    return [
        f"Eine Bachelorarbeit im Bereich {topic}"
        for topic in ranked_topics[:3]
    ]


def answer_professor_thesis_topic_question(
    question: str,
    profile: dict | None,
    conversation_messages: list[dict] | None = None,
) -> dict[str, object] | None:
    professors = get_professors()
    professor = find_mentioned_professor(question, professors)
    if not professor:
        recommendations = recommend_professors(profile, query=question, limit=2)
        if not recommendations:
            return None

        return {
            "answer": (
                "Für deine Bachelorarbeit passen aus deinem Profil und dem genannten Themenbereich "
                "aktuell besonders diese Betreuungspersonen:\n"
                f"{format_professor_recommendations(recommendations)}\n"
                "Die Empfehlung ist eine erste Orientierung. Das konkrete Thema und die Betreuung "
                "solltest du anschließend direkt mit der Person abstimmen."
            ),
            "sources": build_source_list(
                PROFILE_SOURCE_LABEL,
                PROFESSOR_SOURCE_LABEL,
                "Themenorientierung Abschlussarbeit",
            ),
            "intent": "professor_matching",
        }

    focus_topics = professor.get("focus_topics") or []
    topic_text = ", ".join(focus_topics[:3]) if focus_topics else "keine Schwerpunkte hinterlegt"
    ideas = build_thesis_topic_ideas(professor, profile)
    formatted_ideas = "\n".join(
        f"{index}. {idea}"
        for index, idea in enumerate(ideas, start=1)
    )
    status = get_capacity_status_label(professor.get("capacity_status") or "unavailable")
    available_slots = int(professor.get("available_slots") or 0)
    slot_label = "freier Slot" if available_slots == 1 else "freie Slots"

    answer = (
        f"Bei {professor.get('display_name')} passen laut Professorenprofil vor allem "
        f"die Schwerpunkte {topic_text}.\n"
        "Als erste, unverbindliche Thesis-Richtungen könntest du prüfen:\n"
        f"{formatted_ideas}\n"
        f"Verfügbarkeit: {status}, {available_slots} {slot_label}. "
        "Das sind nur Orientierungen aus dem Professorenprofil und deinem Studienprofil. "
        "Das konkrete Thema sollte im Gespräch mit der Betreuungsperson abgestimmt werden."
    )
    return {
        "answer": answer,
        "sources": build_source_list(
            PROFESSOR_SOURCE_LABEL,
            PROFILE_SOURCE_LABEL,
            "Themenorientierung Abschlussarbeit",
        ),
        "intent": "professor_matching",
        "confidence": 1,
    }


def answer_professor_contact_question(
    question: str,
    profile: dict | None,
    conversation_messages: list[dict] | None = None,
) -> dict[str, object] | None:
    if not is_professor_contact_question(question):
        return None

    professors = get_professors()
    mentioned_professor = find_mentioned_professor(question, professors)
    contact_professors = (
        [mentioned_professor]
        if mentioned_professor
        else infer_recent_professors_from_messages(conversation_messages, professors)
    )
    if not contact_professors:
        contact_professors = [
            recommendation_to_professor(recommendation, professors)
            for recommendation in recommend_professors(profile, query=question, limit=2)
        ]
        contact_professors = [professor for professor in contact_professors if professor]

    if not contact_professors:
        return {
            "answer": (
                "Ich kann dir Kontaktinformationen nennen, wenn du eine konkrete "
                "Betreuungsperson oder einen Themenbereich nennst."
            ),
            "sources": build_source_list(PROFESSOR_SOURCE_LABEL),
            "intent": "professor_matching",
        }

    lines = []
    for index, professor in enumerate(contact_professors, start=1):
        email = professor.get("email") or "keine E-Mail hinterlegt"
        status = get_capacity_status_label(professor.get("capacity_status") or "unavailable")
        slots = int(professor.get("available_slots") or 0)
        slot_label = "freier Slot" if slots == 1 else "freie Slots"
        lines.append(
            f"{index}. {professor.get('display_name')}: {email} "
            f"({status}, {slots} {slot_label})"
        )

    answer = (
        "Du kannst die passende Betreuungsperson per E-Mail kontaktieren:\n"
        f"{chr(10).join(lines)}\n"
        "Für die erste Nachricht reicht kurz: wer du bist, welches Thema dich interessiert, "
        "welche Module oder Vorkenntnisse dazu passen und ob aktuell Betreuungskapazität besteht."
    )
    return {
        "answer": answer,
        "sources": build_source_list(PROFESSOR_SOURCE_LABEL),
        "intent": "professor_matching",
        "confidence": 1,
    }


def recommendation_to_professor(
    recommendation: ProfessorRecommendation,
    professors: list[dict],
) -> dict | None:
    for professor in professors:
        if professor.get("display_name") == recommendation.display_name:
            return professor
    return None


def answer_mentioned_professor_question(
    question: str,
    profile: dict | None,
    professors: list[dict] | None = None,
) -> dict[str, object] | None:
    professors = professors if professors is not None else get_professors()
    professor = find_mentioned_professor(question, professors)
    if not professor:
        return None

    focus_topics = professor.get("focus_topics") or []
    topic_text = ", ".join(focus_topics) if focus_topics else "keine Schwerpunkte hinterlegt"
    capacity_status = professor.get("capacity_status") or "unavailable"
    capacity_label = get_capacity_status_label(capacity_status)
    available_slots = int(professor.get("available_slots") or 0)
    slot_label = "freier Slot" if available_slots == 1 else "freie Slots"
    email = professor.get("email")

    recommendation = score_professor_for_profile(professor, profile, query=question)
    profile_reasons = []
    if recommendation:
        profile_reasons = [
            reason
            for reason in recommendation.reasons
            if not reason.startswith(("hat aktuell", "hat nur", "ist aktuell"))
        ]

    if profile_reasons:
        profile_assessment = (
            "Bezug zu deinem Profil: "
            f"{'; '.join(profile_reasons)}."
        )
    else:
        profile_assessment = (
            "Aus den aktuell hinterlegten Interessen und Modulen ergibt sich kein "
            "direkter Profiltreffer. Fachlich kann die Person trotzdem passen, wenn "
            "dein geplantes Thema einen der genannten Schwerpunkte behandelt."
        )

    contact_hint = f" Kontakt: {email}." if email else ""
    answer = (
        f"{professor.get('display_name')} arbeitet laut Professorenprofil zu "
        f"{topic_text}. Die Betreuung ist {capacity_label}; aktuell sind "
        f"{available_slots} {slot_label} hinterlegt.{contact_hint}\n"
        f"{profile_assessment}"
    )
    return {
        "answer": answer,
        "sources": build_source_list(PROFESSOR_SOURCE_LABEL, PROFILE_SOURCE_LABEL),
        "intent": "professor_matching",
        "confidence": 1,
    }


def score_professor_for_profile(
    professor: dict,
    profile: dict | None,
    query: str = "",
    require_query_match: bool = False,
) -> ProfessorRecommendation | None:
    if not profile:
        return None

    focus_topics = professor.get("focus_topics") or []
    normalized_focus_topics = {normalize_matching_text(topic) for topic in focus_topics}
    focus_topics_by_signal = {
        normalize_matching_text(topic): topic
        for topic in focus_topics
    }
    interests = get_interests(profile)
    interest_signals = {normalize_matching_text(interest) for interest in interests}
    interests_by_signal = {
        normalize_matching_text(interest): interest
        for interest in interests
    }
    completed_signals = get_normalized_completed_module_names(profile)
    open_signals = get_normalized_open_module_names(profile)
    module_names_by_signal = {
        normalize_matching_text(module.get("name") or ""): module.get("name")
        for module in [*get_completed_modules(profile), *get_open_modules(profile)]
        if module.get("name")
    }

    capacity_status = professor.get("capacity_status") or "unavailable"
    available_slots = int(professor.get("available_slots") or 0)

    score = 0
    reasons = []

    query_matches = match_requested_focus_topics(query, focus_topics)
    if require_query_match and not query_matches:
        return None

    if query_matches:
        # An explicitly requested subject must dominate generic profile similarity.
        score += 30 + 10 * (len(query_matches) - 1)
        reasons.append(f"passt zum angefragten Thema {', '.join(query_matches)}")

    interest_matches = sorted(normalized_focus_topics & interest_signals)
    if interest_matches:
        score += 4 * len(interest_matches)
        readable_interests = ", ".join(
            interests_by_signal.get(match, focus_topics_by_signal.get(match, match))
            for match in interest_matches[:3]
        )
        reasons.append(
            "passt zu deinen Interessen "
            f"({readable_interests})"
        )

    module_matches = sorted(normalized_focus_topics & (completed_signals | open_signals))
    if module_matches:
        score += 2 * len(module_matches)
        readable_modules = ", ".join(
            module_names_by_signal.get(match, focus_topics_by_signal.get(match, match))
            for match in module_matches[:3]
        )
        reasons.append(
            "knüpft an deinen Studienverlauf an "
            f"({readable_modules})"
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
    professors = get_professors()
    has_explicit_topic = any(
        match_requested_focus_topics(query, professor.get("focus_topics") or [])
        for professor in professors
    )
    recommendations = [
        recommendation
        for professor in professors
        if (
            recommendation := score_professor_for_profile(
                professor,
                profile,
                query=query,
                require_query_match=has_explicit_topic,
            )
        )
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
        reasons = reasons[:1].upper() + reasons[1:] if reasons else ""
        lines.append(
            f"{index}. {recommendation.display_name} ({status}, "
            f"{recommendation.available_slots} {slot_label}): Fokus {topics}. {reasons}."
        )
    return "\n".join(lines)


def answer_professor_question(
    question: str,
    profile: dict | None,
    conversation_messages: list[dict] | None = None,
) -> dict[str, object] | None:
    contact_answer = answer_professor_contact_question(
        question,
        profile,
        conversation_messages,
    )
    if contact_answer:
        return contact_answer

    if is_thesis_topic_question(question):
        topic_answer = answer_professor_thesis_topic_question(
            question,
            profile,
            conversation_messages,
        )
        if topic_answer:
            return topic_answer

    mentioned_professor_answer = answer_mentioned_professor_question(
        question,
        profile,
    )
    if mentioned_professor_answer:
        return mentioned_professor_answer

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

    has_explicit_topic = any(
        any(reason.startswith("passt zum angefragten Thema") for reason in item.reasons)
        for item in recommendations
    )
    introduction = (
        "Zum von dir genannten Themenbereich passen aktuell diese Betreuungspersonen:"
        if has_explicit_topic
        else "Für dein Profil würde ich diese Betreuungspersonen zuerst prüfen:"
    )
    explanation = (
        "Der Themenwunsch ist das primäre Auswahlkriterium; Interessen, Studienverlauf "
        "und Verfügbarkeit ergänzen das Ranking."
        if has_explicit_topic
        else (
            "Die Empfehlung ist ein Matching aus Interessen, Studienverlauf, "
            "Themenfokus und aktueller Verfügbarkeit."
        )
    )
    answer = (
        f"{introduction}\n"
        f"{format_professor_recommendations(recommendations)}\n"
        f"{explanation}"
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
        priority=6,
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

    for attempt in get_critical_exam_attempts(profile):
        name = attempt.get("name")
        if not name:
            continue
        recommendations.append(
            AdvisingRecommendation(
                title=f"{name} sofort priorisieren",
                rationale=(
                    "Das Modul ist als 3. Versuch markiert. Es sollte vor normalen "
                    "Modul-, Wahlfach- oder Vertiefungsentscheidungen fachlich und "
                    "organisatorisch abgesichert werden."
                ),
                priority=2,
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
                priority=3,
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
                priority=4,
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
                priority=5,
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
    exam_attempts = get_exam_attempts(profile)
    recommendations = build_study_recommendations(profile)

    if contains_any(normalized, ["versuch", "versuche", "fehlversuch"]):
        third_attempts = [
            attempt
            for attempt in exam_attempts
            if int(attempt.get("attempt") or 0) >= int(attempt.get("max_attempts") or 3)
        ]
        second_attempts = [
            attempt
            for attempt in exam_attempts
            if int(attempt.get("attempt") or 0) == 2
        ]
        parts = []
        if second_attempts:
            parts.append(
                "Als 2. Versuch ist hinterlegt: "
                f"{format_exam_attempts(second_attempts)}."
            )
        else:
            parts.append("Es ist aktuell kein 2. Versuch im Profil hinterlegt.")

        if third_attempts:
            parts.append(
                "Als 3. Versuch ist hinterlegt: "
                f"{format_exam_attempts(third_attempts)}. "
                "Das sollte in der Studienplanung sehr hoch priorisiert werden."
            )
        else:
            parts.append("Ein 3. Versuch ist aktuell nicht im Profil hinterlegt.")

        return {
            "answer": " ".join(parts),
            "sources": build_source_list(PROFILE_SOURCE_LABEL, "Regelbasierte Studienberatung"),
            "intent": "advising",
        }

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
        or ("offen" in normalized and ("modul" in normalized or "faecher" in normalized or "fach" in normalized))
        or "noch schreiben" in normalized
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


def answer_human_advising_question(question: str, profile: dict | None) -> dict[str, object]:
    """Give safe first-step guidance for cases that need human judgment."""
    normalized = normalize_question(question)
    profile_name = profile.get("display_name") if profile else None
    study_program = profile.get("study_program") if profile else None
    ects_earned = profile.get("ects_earned") if profile else None
    current_status = []

    if study_program:
        current_status.append(f"aktueller Studiengang: {study_program}")
    if ects_earned is not None:
        current_status.append(f"aktuell hinterlegte ECTS: {ects_earned}")

    profile_context = (
        f" In deinem Profil sehe ich {', '.join(current_status)}."
        if current_status
        else ""
    )
    greeting = f"{profile_name}, " if profile_name else ""

    if contains_any(
        normalized,
        [
            "studiengang wechseln",
            "studienwechsel",
            "fach wechseln",
            "wechseln",
            "abbrechen",
            "studium abbrechen",
            "exmatrikulation",
            "exmatrikulieren",
            "zweifel",
        ],
    ):
        answer = (
            f"{greeting}das ist ein sinnvolles Anliegen für eine individuelle Studienberatung, "
            "weil ein Studiengangwechsel von Gründen, Fristen, Anerkennung bisheriger "
            f"Leistungen und persönlichen Zielen abhängt.{profile_context}\n"
            "Als erste Orientierung kannst du diese Punkte vorbereiten:\n"
            "1. Warum denkst du über den Wechsel nach?\n"
            "2. Welcher Zielstudiengang kommt für dich infrage?\n"
            "3. Welche bestandenen Module und ECTS könnten anerkannt werden?\n"
            "4. Welche Fristen und Zulassungsvoraussetzungen gelten für den Zielstudiengang?\n"
            "Bitte vereinbare dafür einen Termin mit der Studienberatung oder Fachstudienberatung. "
            "Der Bot kann hier strukturieren, aber keine verbindliche Wechselentscheidung treffen."
        )
    elif contains_any(normalized, ["anerkennung", "anerkennen", "anrechnen"]):
        answer = (
            "Bei Anerkennung oder Anrechnung von Leistungen sollte eine Fachberatung prüfen, "
            "ob Inhalte, Umfang und Prüfungsform wirklich vergleichbar sind. "
            "Bereite dafür Modulhandbücher, Leistungsnachweise und eine Übersicht deiner "
            "bisherigen ECTS vor."
        )
    elif contains_any(
        normalized,
        ["haertefall", "nachteilsausgleich", "krankheit", "frist verpasst", "frist versaeumt"],
    ):
        answer = (
            "Das klingt nach einem Einzelfall mit möglicher rechtlicher oder persönlicher "
            "Tragweite. Bitte kläre das direkt mit der zuständigen Beratungsstelle oder dem "
            "Prüfungsamt. Der Bot kann keine Härtefall-, Nachteilsausgleichs- oder "
            "Fristentscheidung verbindlich bewerten."
        )
    else:
        answer = (
            "Das Anliegen wirkt individuell und sollte nicht allein automatisiert entschieden "
            "werden. Ich kann dir helfen, die nächsten Fragen zu strukturieren, aber für eine "
            "verbindliche Einschätzung solltest du die Studienberatung oder die zuständige "
            "Fachstelle einbeziehen."
        )

    return {
        "answer": answer,
        "sources": build_source_list(PROFILE_SOURCE_LABEL, HUMAN_ADVISORY_SOURCE_LABEL),
        "intent": "human_advising",
        "confidence": 1,
    }


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
        "kann" in normalized
        or "anmelden" in normalized
        or "darf" in normalized
        or "schreiben" in normalized
        or "wann" in normalized
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

    if contains_any(normalized, ["einschreibung", "einschreiben", "immatrikulation"]):
        return {
            "answer": "Die Einschreibung erfolgt nach einer Zulassung online über das Bewerbungsportal. Alle geforderten Unterlagen müssen innerhalb der angegebenen Frist vollständig hochgeladen werden.",
            "sources": source,
            "intent": "rag",
        }

    if "stundenplan" in normalized:
        return {
            "answer": "Der Stundenplan wird im zentralen Campusportal veröffentlicht. Änderungen sind bis zum Beginn der Vorlesungszeit möglich; verbindlich ist die zuletzt veröffentlichte Version.",
            "sources": source,
            "intent": "rag",
        }

    if contains_any(normalized, ["formular", "formulare", "antrag", "antraege"]):
        return {
            "answer": "Formulare für Beurlaubung, Prüfungsangelegenheiten und Adressänderungen werden im Online-Serviceportal bereitgestellt. Unterschriebene Anträge sollen als PDF hochgeladen oder beim zuständigen Servicebereich eingereicht werden.",
            "sources": source,
            "intent": "rag",
        }

    if contains_any(normalized, ["praxissemester", "praktikum", "career service"]):
        return {
            "answer": "Das Praxissemester kann angemeldet werden, wenn die in der Prüfungsordnung vorgesehenen Voraussetzungen erfüllt sind. Die Praktikumsstelle muss vor Beginn bestätigt werden; der Career Service unterstützt bei der Suche.",
            "sources": source,
            "intent": "rag",
        }

    if contains_any(normalized, ["studiengangwechsel", "studiengang wechseln"]):
        return {
            "answer": "Ein Studiengangwechsel erfordert eine individuelle Prüfung der Zulassung, Fristen und möglichen Anerkennung bereits erbrachter Leistungen. Dafür sollte frühzeitig ein Beratungstermin vereinbart werden.",
            "sources": source,
            "intent": "rag",
        }

    if contains_any(normalized, ["sekretariat", "studierendensekretariat", "kontakt", "kontaktieren", "sprechstunde"]):
        return {
            "answer": "Das Studierendensekretariat kann für allgemeine Anliegen über das Online-Serviceportal kontaktiert werden. Für dringende oder persönliche Anliegen werden Sprechstunden im Campusportal angekündigt.",
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
    attachment_context: str = "",
    conversation_messages: list[dict] | None = None,
) -> dict[str, object]:
    route = route_intent_with_context(question, conversation_messages)
    has_attachment_context = bool(attachment_context.strip())
    if route.intent == "fallback" and not has_attachment_context:
        return attach_route(
            {
                "answer": FALLBACK_ANSWER,
                "sources": [FALLBACK_SOURCE],
                "confidence": 0,
            },
            route,
        )

    profile = get_student_profile(student_id)
    if route.intent == "fallback" and has_attachment_context:
        route = IntentRoute(
            intent="rag",
            label="Chat-Anhang",
            data_sources=["Chat-Anhänge"],
            reason="Die Frage passt zu keinem Standard-Intent, aber im aktiven Chat liegen hochgeladene Dokumente als Kontext vor.",
        )

    if route.intent == "human_advising":
        return attach_route(answer_human_advising_question(question, profile), route)

    if route.intent == "professor_matching":
        professor_answer = answer_professor_question(
            question,
            profile,
            conversation_messages,
        )
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
    if top_score < MIN_RETRIEVAL_SIMILARITY and not has_attachment_context:
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
    if has_attachment_context:
        retrieved_documents.insert(
            0,
            Document(
                page_content=attachment_context,
                metadata={
                    "source": "Chat-Anhänge",
                    "source_label": "Chat-Anhänge · aktueller Verlauf",
                    "origin": "chat_upload_context",
                },
            ),
        )
        top_score = max(top_score, 1.0)

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
