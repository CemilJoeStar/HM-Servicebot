import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const STUDENT_ID = "demo-student-001";
const EXAMPLE_QUESTIONS = [
  "Bis wann muss ich mich für das Sommersemester rückmelden?",
  "Ab wie vielen ECTS kann ich die Bachelorarbeit anmelden?",
  "Wie lange vor einer Prüfung kann ich mich abmelden?",
];
const INITIAL_MESSAGES = [
  {
    role: "assistant",
    text: "Hallo, ich helfe dir bei Fragen zu Rückmeldung, Bachelorarbeit, Prüfungsabmeldung und Studierendenausweis.",
  },
];

function App() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [savedChats, setSavedChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [status, setStatus] = useState("Bereit.");
  const [statusType, setStatusType] = useState("idle");
  const [hasIndexed, setHasIndexed] = useState(true);
  const [isAsking, setIsAsking] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [studentProfile, setStudentProfile] = useState(null);

  useEffect(() => {
    async function loadInitialData() {
      try {
        const [profileResponse, chatsResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/students/${STUDENT_ID}`),
          fetch(`${API_BASE_URL}/api/students/${STUDENT_ID}/chats`),
        ]);
        const profileData = await profileResponse.json();
        const chatsData = await chatsResponse.json();

        if (!profileResponse.ok) {
          throw new Error(
            profileData.detail || "Studentenprofil konnte nicht geladen werden."
          );
        }
        if (!chatsResponse.ok) {
          throw new Error(chatsData.detail || "Chats konnten nicht geladen werden.");
        }

        setStudentProfile(profileData);
        setSavedChats(chatsData);
      } catch (error) {
        setAppStatus(error.message, "error");
      }
    }

    loadInitialData();
  }, []);

  function setAppStatus(message, type = "idle") {
    setStatus(message);
    setStatusType(type);
  }

  function startNewChat() {
    setMessages(INITIAL_MESSAGES);
    setActiveChatId(null);
    setQuestion("");
    setAppStatus("Neuer Chat gestartet.", "success");
  }

  async function openSavedChat(chat) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${chat.id}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Chat konnte nicht geladen werden.");
      }

      setMessages(data.messages);
      setActiveChatId(data.id);
      setQuestion("");
      setAppStatus(`${data.title} geladen.`, "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    }
  }

  async function ingestFaq() {
    setIsIngesting(true);
    setAppStatus("FAQ wird indexiert...", "loading");

    try {
      const response = await fetch(`${API_BASE_URL}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Ingestion fehlgeschlagen.");
      }

      setHasIndexed(true);
      setAppStatus("Wissensbasis ist bereit.", "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    } finally {
      setIsIngesting(false);
    }
  }

  async function askQuestion(event) {
    event.preventDefault();

    const userQuestion = question.trim();
    if (!userQuestion) {
      setAppStatus("Bitte gib zuerst eine Frage ein.", "error");
      return;
    }

    setIsAsking(true);
    setAppStatus("Suche passende Informationen...", "loading");
    setQuestion("");
    setMessages((currentMessages) => [
      ...currentMessages,
      { role: "user", text: userQuestion },
    ]);

    try {
      const response = await fetch(`${API_BASE_URL}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: userQuestion, student_id: STUDENT_ID }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Antwort konnte nicht generiert werden.");
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        { role: "assistant", text: data.answer },
      ]);
      setAppStatus("Bereit.", "idle");
    } catch (error) {
      setAppStatus(error.message, "error");
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          role: "assistant",
          text: "Die Antwort konnte gerade nicht erstellt werden. Bitte versuche es erneut.",
        },
      ]);
    } finally {
      setIsAsking(false);
    }
  }

  return (
    <main className="appShell">
      <aside className="leftRail">
        <div className="railBrand">
          <div className="hmLogo" aria-label="Hochschule München">
            <span className="hmLetters">HM</span>
            <span className="hmSquare" />
            <span className="hmText">
              Hochschule
              <br />
              München
              <br />
              University of
              <br />
              Applied Sciences
            </span>
          </div>
          <div className="productTitle">
            <p className="eyebrow">Service-Bot</p>
            <h1>Studierendenservice</h1>
          </div>
        </div>

        <button className="newChatButton" type="button" onClick={startNewChat}>
          Neuer Chat
        </button>

        {savedChats.length > 0 && (
          <section className="savedChats">
            <h2>Gespeicherte Chats</h2>
            {savedChats.map((chat) => (
              <button
                className={activeChatId === chat.id ? "savedChat active" : "savedChat"}
                key={chat.id}
                type="button"
                onClick={() => openSavedChat(chat)}
              >
                <span>{chat.title}</span>
                <small>{chat.meta}</small>
              </button>
            ))}
          </section>
        )}
      </aside>

      <section className="chatLayout">
        <div className="conversation" aria-live="polite">
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <div className="avatar">{message.role === "assistant" ? "HM" : "du"}</div>
              <p>{message.text}</p>
            </article>
          ))}

          {isAsking && (
            <article className="message assistant">
              <div className="avatar">HM</div>
              <p>Ich suche die passende Information...</p>
            </article>
          )}
        </div>

        <div className="suggestions">
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              className="suggestionButton"
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
            >
              {example}
            </button>
          ))}
        </div>

        {statusType !== "idle" && <div className={`statusBox ${statusType}`}>{status}</div>}

        <form className="composer" onSubmit={askQuestion}>
          <textarea
            aria-label="Studentische Frage"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Frage zum Studium stellen..."
            rows={1}
          />
          <button className="sendButton" type="submit" disabled={isAsking || isIngesting}>
            {isAsking ? "..." : "Senden"}
          </button>
        </form>

        <details className="adminPanel">
          <summary>Wissensbasis verwalten</summary>
          <div className="adminContent">
            <p>
              Die Wissensbasis ist für RAG technisch nötig, aber für Studierende
              kein normaler Bedien-Schritt.
            </p>
            <button className="secondaryButton" onClick={ingestFaq} disabled={isIngesting || isAsking}>
              {isIngesting ? "Indexiere..." : "FAQ neu indexieren"}
            </button>
            <span className={hasIndexed ? "indexPill ready" : "indexPill"}>
              {hasIndexed ? "Index bereit" : "Nicht indexiert"}
            </span>
          </div>
        </details>
      </section>

      <aside className="rightRail">
        <section className="infoCard">
          <h2>Studentenprofil</h2>
          {studentProfile ? (
            <dl className="profileList">
              <div>
                <dt>Name</dt>
                <dd>{studentProfile.display_name}</dd>
              </div>
              <div>
                <dt>Studiengang</dt>
                <dd>{studentProfile.study_program}</dd>
              </div>
              <div>
                <dt>Semester</dt>
                <dd>{studentProfile.semester}</dd>
              </div>
              <div>
                <dt>ECTS</dt>
                <dd>{studentProfile.ects_earned}</dd>
              </div>
              <div>
                <dt>Semesterbeitrag</dt>
                <dd>{studentProfile.semester_fee_paid ? "bezahlt" : "nicht bezahlt"}</dd>
              </div>
              <div>
                <dt>Bachelorarbeit</dt>
                <dd>{studentProfile.thesis_registered ? "angemeldet" : "nicht angemeldet"}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">Profil wird geladen...</p>
          )}
        </section>

        <section className="infoCard">
          <h2>Wissensbasis</h2>
          <p className="muted">
            Offizielle Regeln kommen aus den FAQ-Chunks. Profildaten werden nur
            zur Personalisierung genutzt.
          </p>
          <span className={hasIndexed ? "indexPill ready" : "indexPill"}>
            {hasIndexed ? "Index bereit" : "Nicht indexiert"}
          </span>
        </section>
      </aside>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
