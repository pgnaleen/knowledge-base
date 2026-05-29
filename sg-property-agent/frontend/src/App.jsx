import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const WA_NUMBER = import.meta.env.VITE_WHATSAPP_NUMBER || "";

const STARTER_PROMPTS = [
  { icon: "🏠", title: "First-time PR Condo", text: "What is ABSD for a PR buying their first condo?" },
  { icon: "🏦", title: "HDB Eligibility", text: "Can a PR couple buy an HDB flat and what are the conditions?" },
  { icon: "📊", title: "Duty Estimate", text: "Estimate stamp duties for a 1.2M residential purchase." },
  { icon: "📅", title: "Timeline Risk", text: "If I sell within 2 years, how does SSD apply?" },
];

const TOPIC_PILLS = ["ABSD", "HDB Rules", "BSD / SSD", "PR & Foreigner", "Condo / EC"];

function IconBuilding() {
  return (
    <svg className="sidebar-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21h18M5 21V5a2 2 0 012-2h10a2 2 0 012 2v16M9 21v-8h6v8M9 7h.01M15 7h.01M9 11h.01M15 11h.01" />
    </svg>
  );
}

function IconUser() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
      <path d="M12 12a5 5 0 100-10 5 5 0 000 10zm0 2c-5.33 0-8 2.67-8 4v1h16v-1c0-1.33-2.67-4-8-4z" />
    </svg>
  );
}

function IconBot() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
      <path d="M12 2l2.4 7.4L22 12l-7.6 2.6L12 22l-2.4-7.4L2 12l7.6-2.6L12 2z" />
    </svg>
  );
}

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
      <path d="M2 21L23 12 2 3v7l15 2-15 2v7z" />
    </svg>
  );
}

function IconMenu() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="22" height="22">
      <path d="M3 12h18M3 6h18M3 18h18" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="22" height="22">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}

function IconWhatsApp() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
    </svg>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [threadId] = useState(() => crypto.randomUUID());
  const bottom = useRef(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(customQuestion) {
    const question = (customQuestion ?? input).trim();
    if (!question || loading) return;

    setSidebarOpen(false);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setLoading(true);
    setMessages((prev) => [...prev, { role: "agent", text: "", status: "Connecting..." }]);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, thread_id: threadId }),
        credentials: "include",
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          if (event.type === "status") {
            setMessages((prev) => {
              const u = [...prev];
              u[u.length - 1] = { ...u[u.length - 1], status: event.text };
              return u;
            });
          } else if (event.type === "token") {
            setMessages((prev) => {
              const u = [...prev];
              const last = u[u.length - 1];
              u[u.length - 1] = { ...last, text: last.text + event.content, status: null };
              return u;
            });
          } else if (event.type === "done" || event.type === "error") {
            setMessages((prev) => {
              const u = [...prev];
              u[u.length - 1] = {
                ...u[u.length - 1],
                ...(event.type === "error" ? { text: event.text } : {}),
                status: null,
              };
              return u;
            });
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const u = [...prev];
        u[u.length - 1] = {
          role: "agent",
          text: "Could not reach backend on port 8001. Please start the sg-property-agent backend and try again.",
          status: null,
        };
        return u;
      });
    } finally {
      setLoading(false);
    }
  }

  async function reset() {
    try {
      await fetch(`${API}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId }),
        credentials: "include",
      });
      setMessages([]);
    } catch {
      alert("Could not reset conversation");
    }
  }

  return (
    <div className="app-shell">
      <div
        className={`sidebar-backdrop${sidebarOpen ? " open" : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
        <div className="sidebar-brand">
          <div className="sidebar-icon">
            <IconBuilding />
          </div>
          <p className="brand-kicker">SG PROPERTY</p>
          <h1>Property Advisor</h1>
          <p>Official answers for HDB eligibility, ABSD, BSD/SSD, financing, and property decisions.</p>
        </div>

        <button className="reset-btn" onClick={reset}>+ New Chat</button>

        <div className="sidebar-section">
          <p className="sidebar-section-label">Topics</p>
          <div className="pill-wrap">
            {TOPIC_PILLS.map((pill) => (
              <span key={pill} className="pill">{pill}</span>
            ))}
          </div>
        </div>

        <div className="sidebar-section">
          <p className="sidebar-section-label">Sources</p>
          <p className="sidebar-sources">HDB · IRAS · URA · MAS · SLA · BCA · CEA</p>
        </div>

        <div className="metric-card">
          <p className="metric-title">Session</p>
          <div className="metric-row">
            <span>Questions</span>
            <strong>{messages.filter((m) => m.role === "user").length}</strong>
          </div>
          <div className="metric-row">
            <span>Answers</span>
            <strong>{messages.filter((m) => m.role === "agent").length}</strong>
          </div>
        </div>
      </aside>

      <section className="chat-shell">
        <header className="chat-header">
          <div className="header-left">
            <button
              className="hamburger"
              onClick={() => setSidebarOpen((o) => !o)}
              aria-label="Toggle menu"
            >
              {sidebarOpen ? <IconClose /> : <IconMenu />}
            </button>
            <span className="header-brand-mobile">SG Property Advisor</span>
            <h2 className="header-title-desktop">Property Policy Assistant</h2>
          </div>
          <div className="header-right">
            <span className="status-badge">&#9679; Live KB</span>
          </div>
        </header>

        <div className="chat-panel">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <IconBuilding />
              </div>
              <h3>How can I help with your Singapore property question?</h3>
              <p className="empty-subtitle">Powered by official HDB, IRAS, URA, MAS, SLA, BCA &amp; CEA sources</p>
              <div className="scenario-grid">
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt.title}
                    className="scenario-card"
                    onClick={() => send(prompt.text)}
                    disabled={loading}
                  >
                    <span className="scenario-icon">{prompt.icon}</span>
                    <strong>{prompt.title}</strong>
                    <span>{prompt.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((m, i) => (
                <article key={i} className={`message-row ${m.role}`}>
                  <div className="avatar">
                    {m.role === "user" ? <IconUser /> : <IconBot />}
                  </div>
                  <div className="message-bubble">
                    {m.status && (
                      <span className="stream-status">
                        <span className="thinking">
                          <span className="dot" />
                          <span className="dot" />
                          <span className="dot" />
                        </span>
                        {m.status}
                      </span>
                    )}
                    {m.text}
                  </div>
                </article>
              ))}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <footer className="composer-wrap">
          <div className="composer">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="Ask about HDB eligibility, stamp duties, financing..."
              disabled={loading}
            />
            <button onClick={() => send()} disabled={loading || !input.trim()} aria-label="Send">
              <IconSend />
            </button>
          </div>
          <p className="composer-disclaimer">Answers are based on official Singapore government sources. Verify before acting.</p>
        </footer>
      </section>

      {WA_NUMBER && (
        <a
          href={`https://wa.me/${WA_NUMBER}`}
          target="_blank"
          rel="noopener noreferrer"
          className="wa-fab"
          aria-label="Chat on WhatsApp"
        >
          <IconWhatsApp />
          <span className="wa-fab-label">WhatsApp</span>
        </a>
      )}
    </div>
  );
}
