import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

const STARTER_PROMPTS = [
  {
    title: "First-time PR Condo",
    text: "What is ABSD for a PR buying first condo?",
  },
  {
    title: "HDB Eligibility",
    text: "Can a PR couple buy an HDB flat and what are the conditions?",
  },
  {
    title: "Duty Estimate",
    text: "Estimate stamp duties for a 1.2M residential purchase.",
  },
  {
    title: "Timeline Risk",
    text: "If I sell within 2 years, how does SSD apply?",
  },
];

const MARKET_PILLS = ["ABSD", "HDB Rules", "BSD/SSD", "PR/Foreigner", "Condo/HDB"];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottom = useRef(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(customQuestion) {
    const question = (customQuestion ?? input).trim();
    if (!question || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setLoading(true);

    // Insert placeholder agent message — updated in-place as the stream arrives
    setMessages((prev) => [...prev, { role: "agent", text: "", status: "Connecting..." }]);

    try {
      const res = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
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
        buffer = parts.pop(); // keep incomplete trailing line

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
          text: "Could not reach backend on port 8001. Please start sg-property-agent backend and try again.",
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
        credentials: "include",
      });
      setMessages([]);
    } catch {
      alert("Could not reset conversation");
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <p className="brand-kicker">SG PROPERTY</p>
          <h1>Policy Copilot</h1>
          <p>Grounded answers for ABSD, HDB eligibility, BSD/SSD, and buying decisions.</p>
        </div>

        <button className="reset-btn" onClick={reset}>
          New Chat
        </button>

        <div className="pill-wrap">
          {MARKET_PILLS.map((pill) => (
            <span key={pill} className="pill">
              {pill}
            </span>
          ))}
        </div>

        <div className="metric-card">
          <p className="metric-title">Session</p>
          <p>Questions: {messages.filter((m) => m.role === "user").length}</p>
          <p>Answers: {messages.filter((m) => m.role === "agent").length}</p>
        </div>
      </aside>

      <section className="chat-shell">
        <header className="chat-header">
          <h2>Property Policy Assistant</h2>
          <span className="status">Live KB</span>
        </header>

        <div className="chat-panel">
          {messages.length === 0 ? (
            <div className="empty-state">
              <h3>How can I help with your property question?</h3>
              <div className="scenario-grid">
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt.title}
                    className="scenario-card"
                    onClick={() => send(prompt.text)}
                    disabled={loading}
                  >
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
                  <div className="avatar">{m.role === "user" ? "You" : "AI"}</div>
                  <div className="message-bubble">
                    {m.status && <span className="stream-status">{m.status}</span>}
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
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Message SG Property Copilot..."
              disabled={loading}
            />
            <button onClick={() => send()} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
