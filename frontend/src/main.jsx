import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const STUDENT_ID = "demo-student-001";
const EXAMPLE_QUESTIONS = [
  "Bis wann muss ich mich für das Sommersemester rückmelden?",
  "Kann ich meine Bachelorarbeit anmelden?",
  "Welche Module fehlen mir noch?",
  "Welcher Schwerpunkt passt zu mir?",
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
  const [openMenuChatId, setOpenMenuChatId] = useState(null);
  const [shouldSaveChat, setShouldSaveChat] = useState(true);

  const profileNotes = studentProfile?.notes || {};
  const completedModules = Array.isArray(profileNotes.completed_modules)
    ? profileNotes.completed_modules
    : [];
  const openModules = Array.isArray(profileNotes.open_modules)
    ? profileNotes.open_modules
    : [];
  const interests = Array.isArray(profileNotes.interests) ? profileNotes.interests : [];

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

  async function loadSavedChats() {
    const response = await fetch(`${API_BASE_URL}/api/students/${STUDENT_ID}/chats`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Chats konnten nicht geladen werden.");
    }

    setSavedChats(data);
    return data;
  }

  function setAppStatus(message, type = "idle") {
    setStatus(message);
    setStatusType(type);
  }

  function createChatTitle(userQuestion) {
    const cleanedQuestion = userQuestion.replace(/[?.!]+$/g, "").trim();
    if (cleanedQuestion.length <= 34) {
      return cleanedQuestion;
    }
    return `${cleanedQuestion.slice(0, 31).trim()}...`;
  }

  function startNewChat() {
    setMessages(INITIAL_MESSAGES);
    setActiveChatId(null);
    setQuestion("");
    setOpenMenuChatId(null);
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
      setShouldSaveChat(true);
      setQuestion("");
      setOpenMenuChatId(null);
      setAppStatus(`${data.title} geladen.`, "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    }
  }

  async function renameSavedChat(chat) {
    const title = window.prompt("Neuer Chat-Titel", chat.title);
    const cleanedTitle = title?.trim();
    if (!cleanedTitle || cleanedTitle === chat.title) {
      setOpenMenuChatId(null);
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${chat.id}/rename`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: cleanedTitle }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Chat konnte nicht umbenannt werden.");
      }

      await loadSavedChats();
      setAppStatus("Chat umbenannt.", "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    } finally {
      setOpenMenuChatId(null);
    }
  }

  async function togglePinnedChat(chat) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${chat.id}/pin`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned: !chat.pinned }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Chat konnte nicht angeheftet werden.");
      }

      await loadSavedChats();
      setAppStatus(chat.pinned ? "Chat gelöst." : "Chat angeheftet.", "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    } finally {
      setOpenMenuChatId(null);
    }
  }

  async function archiveSavedChat(chat) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${chat.id}/archive`, {
        method: "POST",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Chat konnte nicht archiviert werden.");
      }

      if (activeChatId === chat.id) {
        startNewChat();
      }
      await loadSavedChats();
      setAppStatus("Chat archiviert.", "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    } finally {
      setOpenMenuChatId(null);
    }
  }

  async function deleteSavedChat(chat) {
    const shouldDelete = window.confirm(
      "Diesen Chat entfernen? Der Verlauf wird anonymisiert und aus der Liste entfernt."
    );
    if (!shouldDelete) {
      setOpenMenuChatId(null);
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${chat.id}`, {
        method: "DELETE",
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Chat konnte nicht gelöscht werden.");
      }

      if (activeChatId === chat.id) {
        startNewChat();
      }
      await loadSavedChats();
      setAppStatus("Chat gelöscht.", "success");
    } catch (error) {
      setAppStatus(error.message, "error");
    } finally {
      setOpenMenuChatId(null);
    }
  }

  function handleSavePreferenceChange(event) {
    const isEnabled = event.target.checked;
    setShouldSaveChat(isEnabled);

    if (!isEnabled) {
      setActiveChatId(null);
      setAppStatus("Chat-Speicherung deaktiviert.", "success");
      return;
    }

    setAppStatus("Chat-Speicherung aktiviert.", "success");
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
    const userMessage = { role: "user", text: userQuestion };
    const messagesWithQuestion = [...messages, userMessage];
    setMessages(messagesWithQuestion);

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

      const messagesWithAnswer = [
        ...messagesWithQuestion,
        { role: "assistant", text: data.answer, sources: data.sources || [] },
      ];
      setMessages(messagesWithAnswer);

      if (!shouldSaveChat) {
        setActiveChatId(null);
      } else if (activeChatId) {
        const updateResponse = await fetch(`${API_BASE_URL}/api/chats/${activeChatId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: messagesWithAnswer,
            meta: "gerade eben",
          }),
        });
        const updatedChat = await updateResponse.json();

        if (!updateResponse.ok) {
          throw new Error(updatedChat.detail || "Chat konnte nicht gespeichert werden.");
        }
      } else {
        const createResponse = await fetch(`${API_BASE_URL}/api/chats`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            student_id: STUDENT_ID,
            title: createChatTitle(userQuestion),
            meta: "gerade eben",
            messages: messagesWithAnswer,
          }),
        });
        const createdChat = await createResponse.json();

        if (!createResponse.ok) {
          throw new Error(createdChat.detail || "Chat konnte nicht gespeichert werden.");
        }

        setActiveChatId(createdChat.id);
      }

      if (shouldSaveChat) {
        await loadSavedChats();
      }
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
            <div className="savedChatsHeader">
              <h2>Aktuelle</h2>
              <span aria-hidden="true">⌄</span>
            </div>
            {savedChats.map((chat) => (
              <div
                className={activeChatId === chat.id ? "savedChatItem active" : "savedChatItem"}
                key={chat.id}
              >
                <button
                  className="savedChatMain"
                  type="button"
                  onClick={() => openSavedChat(chat)}
                >
                  <span className="savedChatTitle">
                    {chat.pinned && <span className="pinMark" aria-label="Angeheftet">●</span>}
                    {chat.title}
                  </span>
                  <small className="savedChatMeta">{chat.meta}</small>
                </button>
                <button
                  aria-label={`Optionen für ${chat.title}`}
                  className="chatMenuButton"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    setOpenMenuChatId(openMenuChatId === chat.id ? null : chat.id);
                  }}
                >
                  ⋯
                </button>
                {openMenuChatId === chat.id && (
                  <div className="chatMenu" role="menu">
                    <button type="button" onClick={() => togglePinnedChat(chat)}>
                      {chat.pinned ? "Loslösen" : "Chat anheften"}
                    </button>
                    <button type="button" onClick={() => renameSavedChat(chat)}>
                      Umbenennen
                    </button>
                    <button type="button" onClick={() => archiveSavedChat(chat)}>
                      Archivieren
                    </button>
                    <button
                      className="danger"
                      type="button"
                      onClick={() => deleteSavedChat(chat)}
                    >
                      Löschen
                    </button>
                  </div>
                )}
              </div>
            ))}
          </section>
        )}
      </aside>

      <section className="chatLayout">
        <div className="conversation" aria-live="polite">
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <div className="avatar">{message.role === "assistant" ? "HM" : "du"}</div>
              <div className="messageBubble">
                <p>{message.text}</p>
                {message.role === "assistant" && message.sources?.length > 0 && (
                  <div className="sourceList" aria-label="Verwendete Quellen">
                    {message.sources.map((source) => (
                      <span className="sourcePill" key={source}>
                        <span className="sourceDot" aria-hidden="true" />
                        <strong>Quelle:</strong>
                        <small>{source}</small>
                      </span>
                    ))}
                  </div>
                )}
              </div>
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

        <label className="savePreference">
          <input
            checked={shouldSaveChat}
            type="checkbox"
            onChange={handleSavePreferenceChange}
          />
          <span>
            <strong>Chat speichern</strong>
            <small>30 Tage sichtbar, Löschen anonymisiert den Verlauf</small>
          </span>
        </label>

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

        {studentProfile && (
          <section className="infoCard">
            <h2>Studienverlauf</h2>
            <div className="moduleBlock">
              <h3>Offene Module</h3>
              {openModules.length > 0 ? (
                <ul>
                  {openModules.map((module) => (
                    <li key={module.name}>
                      <span>{module.name}</span>
                      <small>{module.ects} ECTS</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Keine offenen Module hinterlegt.</p>
              )}
            </div>
            <div className="moduleBlock compact">
              <h3>Interessen</h3>
              <div className="tagList">
                {interests.map((interest) => (
                  <span key={interest}>{interest}</span>
                ))}
              </div>
            </div>
            <div className="moduleBlock compact">
              <h3>Bestanden</h3>
              <p className="muted">
                {completedModules.length} Demo-Module hinterlegt
              </p>
            </div>
          </section>
        )}

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
