import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const STUDENT_ID = "demo-student-001";
const EXAMPLE_QUESTIONS = [
  "Bis wann muss ich mich für das Sommersemester rückmelden?",
  "Kann ich meine Bachelorarbeit anmelden?",
  "Welche Wahlpflichtmodule passen zu mir?",
  "Welcher Professor passt zu mir?",
  "Was sollte ich als Nächstes machen?",
];
const MODULE_CATALOG = [
  {
    name: "Data Mining",
    ects: 5,
    focus: "Data Analytics",
    skills: ["data analytics", "statistik", "business intelligence", "datenbanken"],
    minEcts: 90,
  },
  {
    name: "Machine Learning Grundlagen",
    ects: 5,
    focus: "Data Analytics",
    skills: ["data analytics", "statistik", "programmierung 1", "business intelligence"],
    minEcts: 100,
  },
  {
    name: "Cloud-Anwendungen",
    ects: 5,
    focus: "Software Engineering",
    skills: ["software engineering", "programmierung 1", "datenbanken"],
    minEcts: 80,
  },
  {
    name: "IT-Sicherheit",
    ects: 5,
    focus: "Software Engineering",
    skills: ["software engineering", "datenbanken", "digitale prozesse"],
    minEcts: 70,
  },
  {
    name: "Projektseminar",
    ects: 5,
    focus: "Digitale Prozesse",
    skills: ["digitale prozesse", "software engineering", "geschäftsprozessmanagement"],
    minEcts: 100,
  },
  {
    name: "Process Mining",
    ects: 5,
    focus: "Digitale Prozesse",
    skills: ["digitale prozesse", "geschäftsprozessmanagement", "data analytics"],
    minEcts: 90,
  },
];
const STUDY_PLAN_MODULES = [
  { semester: 1, name: "Programmierung 1", ects: 5, area: "Informatik" },
  { semester: 1, name: "Datenbanken", ects: 5, area: "Informatik" },
  { semester: 1, name: "Wirtschaftsinformatik", ects: 5, area: "Grundlagen" },
  { semester: 2, name: "Statistik", ects: 5, area: "Methoden" },
  { semester: 2, name: "Marketing", ects: 5, area: "Wirtschaft" },
  { semester: 2, name: "Wirtschaftsmathematik II", ects: 5, area: "Methoden" },
  { semester: 3, name: "Software Engineering", ects: 5, area: "Informatik" },
  { semester: 3, name: "Geschäftsprozessmanagement", ects: 5, area: "Prozesse" },
  { semester: 3, name: "Business Intelligence", ects: 5, area: "Data" },
  { semester: 4, name: "IT-Sicherheit", ects: 5, area: "Informatik" },
  { semester: 4, name: "Projektseminar", ects: 5, area: "Projekt" },
  { semester: 5, name: "Data Mining", ects: 5, area: "Wahlpflicht" },
  { semester: 5, name: "Cloud-Anwendungen", ects: 5, area: "Wahlpflicht" },
  { semester: 6, name: "Praxissemester", ects: 30, area: "Praxis" },
  { semester: 7, name: "Bachelorarbeit", ects: 12, area: "Abschluss" },
];
const FAILED_MODULES = new Set(["wirtschaftsmathematik ii"]);
const INITIAL_MESSAGES = [
  {
    role: "assistant",
    text: "Hallo, ich helfe dir bei Fragen zu Rückmeldung, Bachelorarbeit, Prüfungsabmeldung und Studierendenausweis.",
  },
];

function normalizeText(value) {
  return value.toLowerCase().replaceAll("ä", "ae").replaceAll("ö", "oe").replaceAll("ü", "ue");
}

function getTopCourseRecommendations(studentProfile, completedModules, openModules, interests) {
  if (!studentProfile) {
    return [];
  }

  const completedNames = new Set(completedModules.map((module) => normalizeText(module.name)));
  const openNames = new Set(openModules.map((module) => normalizeText(module.name)));
  const interestSignals = new Set(interests.map((interest) => normalizeText(interest)));
  const ectsEarned = Number(studentProfile.ects_earned || 0);

  return MODULE_CATALOG.map((module) => {
    const normalizedName = normalizeText(module.name);
    if (completedNames.has(normalizedName) || ectsEarned < module.minEcts) {
      return null;
    }

    const skillSet = new Set(module.skills.map((skill) => normalizeText(skill)));
    let score = 0;
    const reasons = [];

    if (interestSignals.has(normalizeText(module.focus))) {
      score += 5;
      reasons.push(module.focus);
    }

    const matchedSkills = [...skillSet].filter((skill) => completedNames.has(skill));
    score += matchedSkills.length * 2;

    const matchedInterests = [...skillSet].filter((skill) => interestSignals.has(skill));
    score += matchedInterests.length * 2;

    if (openNames.has(normalizedName)) {
      score += 4;
      reasons.push("offen");
    }

    return { ...module, score, reasons };
  })
    .filter(Boolean)
    .sort((left, right) => right.score - left.score || left.name.localeCompare(right.name))
    .slice(0, 3);
}

function getCapacityLabel(status) {
  if (status === "available") {
    return "verfügbar";
  }
  if (status === "limited") {
    return "begrenzt verfügbar";
  }
  return "nicht verfügbar";
}

function getProfessorScore(professor, interests) {
  const topicSet = new Set((professor.focus_topics || []).map((topic) => normalizeText(topic)));
  const interestSet = new Set(interests.map((interest) => normalizeText(interest)));
  const topicMatches = [...topicSet].filter((topic) => interestSet.has(topic)).length;
  const capacityScore =
    professor.capacity_status === "available"
      ? 4
      : professor.capacity_status === "limited"
        ? 1
        : -4;

  return topicMatches * 4 + Number(professor.available_slots || 0) + capacityScore;
}

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
  const [professors, setProfessors] = useState([]);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState([]);
  const [openMenuChatId, setOpenMenuChatId] = useState(null);
  const [shouldSaveChat, setShouldSaveChat] = useState(true);
  const [activeView, setActiveView] = useState("chat");

  const profileNotes = studentProfile?.notes || {};
  const completedModules = Array.isArray(profileNotes.completed_modules)
    ? profileNotes.completed_modules
    : [];
  const openModules = Array.isArray(profileNotes.open_modules)
    ? profileNotes.open_modules
    : [];
  const interests = Array.isArray(profileNotes.interests) ? profileNotes.interests : [];
  const missingThesisEcts = studentProfile
    ? Math.max(120 - Number(studentProfile.ects_earned || 0), 0)
    : 0;
  const advisingSteps = studentProfile
    ? [
        !studentProfile.semester_fee_paid && {
          label: "Rückmeldung abschließen",
          detail: "Semesterbeitrag ist noch nicht bezahlt.",
        },
        missingThesisEcts > 0 && {
          label: `${missingThesisEcts} ECTS bis zur Bachelorarbeit`,
          detail: "Voraussetzung: mindestens 120 ECTS.",
        },
        openModules[0] && {
          label: `${openModules[0].name} priorisieren`,
          detail: `${openModules[0].ects} ECTS im Studienverlauf offen.`,
        },
        interests[0] && {
          label: `${interests[0]} als Schwerpunkt prüfen`,
          detail: "Aus Interessen und bestandenen Modulen abgeleitet.",
        },
      ].filter(Boolean)
    : [];
  const recommendedCourses = getTopCourseRecommendations(
    studentProfile,
    completedModules,
    openModules,
    interests
  );
  const rankedProfessors = [...professors]
    .map((professor) => ({
      ...professor,
      score: getProfessorScore(professor, interests),
    }))
    .sort((left, right) => {
      if (left.capacity_status === "unavailable" && right.capacity_status !== "unavailable") {
        return 1;
      }
      if (right.capacity_status === "unavailable" && left.capacity_status !== "unavailable") {
        return -1;
      }
      return right.score - left.score || right.available_slots - left.available_slots;
    });
  const completedModuleNames = new Set(completedModules.map((module) => normalizeText(module.name)));
  const openModuleNames = new Set(openModules.map((module) => normalizeText(module.name)));
  const studyPlanModules = STUDY_PLAN_MODULES.map((module) => {
    const normalizedName = normalizeText(module.name);
    let status = "notStarted";

    if (completedModuleNames.has(normalizedName)) {
      status = "passed";
    } else if (openModuleNames.has(normalizedName)) {
      status = "open";
    } else if (FAILED_MODULES.has(normalizedName)) {
      status = "failed";
    }

    return { ...module, status };
  });
  const studyPlanBySemester = studyPlanModules.reduce((groups, module) => {
    const semester = String(module.semester);
    return {
      ...groups,
      [semester]: [...(groups[semester] || []), module],
    };
  }, {});

  useEffect(() => {
    async function loadInitialData() {
      try {
        const [
          profileResponse,
          chatsResponse,
          professorsResponse,
          knowledgeResponse,
        ] = await Promise.all([
          fetch(`${API_BASE_URL}/api/students/${STUDENT_ID}`),
          fetch(`${API_BASE_URL}/api/students/${STUDENT_ID}/chats`),
          fetch(`${API_BASE_URL}/api/professors`),
          fetch(`${API_BASE_URL}/api/knowledge-documents`),
        ]);
        const profileData = await profileResponse.json();
        const chatsData = await chatsResponse.json();
        const professorsData = await professorsResponse.json();
        const knowledgeData = await knowledgeResponse.json();

        if (!profileResponse.ok) {
          throw new Error(
            profileData.detail || "Studentenprofil konnte nicht geladen werden."
          );
        }
        if (!chatsResponse.ok) {
          throw new Error(chatsData.detail || "Chats konnten nicht geladen werden.");
        }
        if (!professorsResponse.ok) {
          throw new Error(professorsData.detail || "Professoren konnten nicht geladen werden.");
        }
        if (!knowledgeResponse.ok) {
          throw new Error(knowledgeData.detail || "Wissensbasis konnte nicht geladen werden.");
        }

        setStudentProfile(profileData);
        setSavedChats(chatsData);
        setProfessors(professorsData);
        setKnowledgeDocuments(knowledgeData);
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
    setActiveView("chat");
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
      setActiveView("chat");
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
        {
          role: "assistant",
          text: data.answer,
          sources: data.sources || [],
          routeLabel: data.route_label,
          routeReason: data.route_reason,
        },
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

      <section className={activeView === "chat" ? "chatLayout" : "focusLayout"}>
        {activeView === "chat" && (
          <>
            <div className="conversation" aria-live="polite">
              {messages.map((message, index) => (
                <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
                  <div className="avatar">{message.role === "assistant" ? "HM" : "du"}</div>
                  <div className="messageBubble">
                    <p>{message.text}</p>
                    {message.role === "assistant" && message.routeLabel && (
                      <div className="routeMeta" title={message.routeReason || ""}>
                        Route: {message.routeLabel}
                      </div>
                    )}
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
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Frage zum Studium stellen..."
                rows={1}
              />
              <button className="sendButton" type="submit" disabled={isAsking || isIngesting}>
                {isAsking ? "..." : "Senden"}
              </button>
            </form>
          </>
        )}

        {activeView === "profile" && (
          <div className="focusView">
            <button className="backButton" type="button" onClick={() => setActiveView("chat")}>
              Zurück zum Chat
            </button>
            <header className="focusHeader">
              <p className="eyebrow">Studierendenakte</p>
              <h2>Studentenprofil</h2>
              <p>Die Daten dienen der Personalisierung von Antworten und Empfehlungen.</p>
            </header>
            {studentProfile ? (
              <dl className="profileGrid">
                <div><dt>Name</dt><dd>{studentProfile.display_name}</dd></div>
                <div><dt>Studiengang</dt><dd>{studentProfile.study_program}</dd></div>
                <div><dt>Semester</dt><dd>{studentProfile.semester}</dd></div>
                <div><dt>ECTS</dt><dd>{studentProfile.ects_earned}</dd></div>
                <div><dt>Semesterbeitrag</dt><dd>{studentProfile.semester_fee_paid ? "bezahlt" : "nicht bezahlt"}</dd></div>
                <div><dt>Bachelorarbeit</dt><dd>{studentProfile.thesis_registered ? "angemeldet" : "nicht angemeldet"}</dd></div>
              </dl>
            ) : (
              <p className="muted">Profil wird geladen...</p>
            )}
          </div>
        )}

        {activeView === "study" && (
          <div className="focusView">
            <button className="backButton" type="button" onClick={() => setActiveView("chat")}>
              Zurück zum Chat
            </button>
            <header className="focusHeader">
              <p className="eyebrow">Studienverlauf</p>
              <h2>Modulstatus nach Semester</h2>
              <p>Bestandene, offene und noch nicht angetretene Module werden getrennt sichtbar.</p>
            </header>
            <div className="statusLegend">
              <span><i className="passed" /> bestanden</span>
              <span><i className="open" /> offen</span>
              <span><i className="failed" /> Fehlversuch</span>
              <span><i className="notStarted" /> nicht angetreten</span>
            </div>
            <div className="studyPlanGrid">
              {Object.entries(studyPlanBySemester).map(([semester, modules]) => (
                <section className="semesterColumn" key={semester}>
                  <h3>{semester}. Semester</h3>
                  {modules.map((module) => (
                    <article className={`moduleTile ${module.status}`} key={module.name}>
                      <span className="statusIcon" aria-hidden="true" />
                      <strong>{module.name}</strong>
                      <small>{module.ects} ECTS · {module.area}</small>
                    </article>
                  ))}
                </section>
              ))}
            </div>
          </div>
        )}

        {activeView === "recommendations" && (
          <div className="focusView">
            <button className="backButton" type="button" onClick={() => setActiveView("chat")}>
              Zurück zum Chat
            </button>
            <header className="focusHeader">
              <p className="eyebrow">Empfehlungssystem</p>
              <h2>Hybrid-Recommender</h2>
              <p>Module werden aus Interessen, Studienverlauf und ECTS-Voraussetzungen gerankt.</p>
            </header>
            <div className="recommendationBoard">
              {recommendedCourses.map((course) => (
                <article key={course.name}>
                  <span className="scoreBadge">{course.score}</span>
                  <div>
                    <h3>{course.name}</h3>
                    <p>{course.ects} ECTS · {course.focus}</p>
                  </div>
                </article>
              ))}
            </div>
            <ol className="advisingList expanded">
              {advisingSteps.map((step) => (
                <li key={step.label}>
                  <strong>{step.label}</strong>
                  <small>{step.detail}</small>
                </li>
              ))}
            </ol>
          </div>
        )}

        {activeView === "professors" && (
          <div className="focusView">
            <button className="backButton" type="button" onClick={() => setActiveView("chat")}>
              Zurück zum Chat
            </button>
            <header className="focusHeader">
              <p className="eyebrow">Betreuung & Beratung</p>
              <h2>Professorenmatching</h2>
              <p>Betreuungspersonen werden nach Themenfokus, Interessen und freien Kapazitäten gerankt.</p>
            </header>
            <div className="professorGrid">
              {rankedProfessors.map((professor) => (
                <article className={`professorCard ${professor.capacity_status}`} key={professor.id}>
                  <div className="professorCardHeader">
                    <span className="scoreBadge">{professor.score}</span>
                    <span className={`capacityPill ${professor.capacity_status}`}>
                      {getCapacityLabel(professor.capacity_status)}
                    </span>
                  </div>
                  <h3>{professor.display_name}</h3>
                  <p>{professor.department} · {professor.available_slots} freie Slots</p>
                  <div className="tagList">
                    {(professor.focus_topics || []).map((topic) => (
                      <span key={`${professor.id}-${topic}`}>{topic}</span>
                    ))}
                  </div>
                  <small>{professor.notes}</small>
                </article>
              ))}
            </div>
          </div>
        )}

        {activeView === "knowledge" && (
          <div className="focusView">
            <button className="backButton" type="button" onClick={() => setActiveView("chat")}>
              Zurück zum Chat
            </button>
            <header className="focusHeader">
              <p className="eyebrow">Wissensbasis</p>
              <h2>Verifizierte Dokumente</h2>
              <p>Regeln und Fristen kommen aus indexierten Quellen. Profildaten werden separat behandelt.</p>
            </header>
            <div className="knowledgeCards">
              {knowledgeDocuments.map((document) => (
                <article key={document.id}>
                  <strong>{document.title}</strong>
                  <small>
                    {document.status} · Version {document.version} · {document.chunk_count} Chunks
                  </small>
                </article>
              ))}
            </div>
            <div className="adminContent focusAdmin">
              <p>Die Wissensbasis ist für RAG technisch nötig, aber für Studierende kein normaler Bedien-Schritt.</p>
              <button className="secondaryButton" onClick={ingestFaq} disabled={isIngesting || isAsking}>
                {isIngesting ? "Indexiere..." : "FAQ neu indexieren"}
              </button>
              <span className={hasIndexed ? "indexPill ready" : "indexPill"}>
                {hasIndexed ? "Index bereit" : "Nicht indexiert"}
              </span>
            </div>
          </div>
        )}
      </section>

      <aside className="rightRail">
        <button
          className={activeView === "profile" ? "viewCard active" : "viewCard"}
          type="button"
          onClick={() => setActiveView("profile")}
        >
          <span>
            <strong>Studentenprofil</strong>
            <small>{studentProfile?.display_name || "Profil laden"}</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>

        <button
          className={activeView === "study" ? "viewCard active" : "viewCard"}
          type="button"
          onClick={() => setActiveView("study")}
        >
          <span>
            <strong>Studienverlauf</strong>
            <small>{completedModules.length} bestanden · {openModules.length} offen</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>

        <button
          className={activeView === "recommendations" ? "viewCard active" : "viewCard"}
          type="button"
          onClick={() => setActiveView("recommendations")}
        >
          <span>
            <strong>Empfehlungen</strong>
            <small>{recommendedCourses.length} Modulvorschläge</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>

        <button
          className={activeView === "professors" ? "viewCard active" : "viewCard"}
          type="button"
          onClick={() => setActiveView("professors")}
        >
          <span>
            <strong>Professoren</strong>
            <small>{rankedProfessors.length} Betreuungspersonen</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>

        <button
          className={activeView === "knowledge" ? "viewCard active" : "viewCard"}
          type="button"
          onClick={() => setActiveView("knowledge")}
        >
          <span>
            <strong>Wissensbasis</strong>
            <small>{hasIndexed ? "Index bereit" : "Nicht indexiert"}</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>

        <button
          className={activeView === "chat" ? "viewCard active compact" : "viewCard compact"}
          type="button"
          onClick={() => setActiveView("chat")}
        >
          <span>
            <strong>Zurück zum Chat</strong>
            <small>Servicebot öffnen</small>
          </span>
          <b aria-hidden="true">›</b>
        </button>
      </aside>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
