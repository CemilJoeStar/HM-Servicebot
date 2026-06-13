"""
Streamlit UI für den minimalen Uni-RAG-Prototyp.

Start:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from rag_prototype import SCRIPT_DIR, ask, ingest


DEFAULT_FAQ_PATH = SCRIPT_DIR / "uni_faq.txt"


st.set_page_config(
    page_title="MIA Studierendenservice",
    layout="centered",
)

st.title("MIA Studierendenservice")
st.caption("Minimaler RAG-Prototyp mit Gemini, LangChain und Supabase pgvector")

with st.sidebar:
    st.header("Ingestion")
    faq_path_text = st.text_input("FAQ-Datei", value=str(DEFAULT_FAQ_PATH))

    if st.button("FAQ indexieren", type="primary"):
        try:
            with st.spinner("Dokument wird gechunked, eingebettet und gespeichert..."):
                ingest(Path(faq_path_text))
            st.success("FAQ wurde erfolgreich indexiert.")
        except Exception as exc:
            st.error(f"Ingestion fehlgeschlagen: {exc}")

    st.divider()
    st.write("Ablauf")
    st.write("1. SQL in Supabase ausführen")
    st.write("2. `.env` ausfüllen")
    st.write("3. FAQ indexieren")
    st.write("4. Frage stellen")


question = st.text_area(
    "Deine Frage",
    placeholder="z.B. Bis wann muss ich mich für das Sommersemester rückmelden?",
    height=100,
)

if st.button("Antwort generieren"):
    if not question.strip():
        st.warning("Bitte gib zuerst eine Frage ein.")
    else:
        try:
            with st.spinner("Suche passende Quellen und frage Gemini..."):
                answer = ask(question.strip(), print_answer=False)
            st.subheader("Antwort")
            st.write(answer)
        except Exception as exc:
            st.error(f"Antwort konnte nicht generiert werden: {exc}")
