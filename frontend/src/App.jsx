import { useState, useRef, useEffect } from "react";

const API = "http://localhost:8001";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottom = useRef(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const question = input.trim();
    if (!question || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "agent", text: data.answer }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          text: "Error: could not reach the agent server. Is the backend running on port 8001?",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function reset() {
    try {
      await fetch(`${API}/reset`, { method: "POST" });
      setMessages([]);
    } catch {
      alert("Could not reset conversation");
    }
  }

  return (
    <div
      style={{
        maxWidth: 720,
        margin: "40px auto",
        fontFamily: "sans-serif",
        padding: "0 16px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <h2 style={{ margin: 0 }}>🏠 SG Property Agent</h2>
        <button
          onClick={reset}
          style={{
            padding: "6px 14px",
            cursor: "pointer",
            borderRadius: 4,
            border: "1px solid #ccc",
            background: "#fff",
          }}
        >
          Reset
        </button>
      </div>

      <div
        style={{
          border: "1px solid #ddd",
          borderRadius: 8,
          padding: 16,
          height: 500,
          overflowY: "auto",
          marginBottom: 12,
        }}
      >
        {messages.length === 0 && (
          <p
            style={{
              color: "#999",
              textAlign: "center",
              marginTop: 200,
              fontSize: 14,
            }}
          >
            Ask a question about Singapore property rules...
            <br />
            <span style={{ fontSize: 12 }}>
              e.g., "What is ABSD for PR buying a condo?"
            </span>
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              textAlign: m.role === "user" ? "right" : "left",
              marginBottom: 12,
            }}
          >
            <span
              style={{
                display: "inline-block",
                maxWidth: "85%",
                padding: "10px 14px",
                borderRadius: 12,
                background: m.role === "user" ? "#0070f3" : "#f1f1f1",
                color: m.role === "user" ? "#fff" : "#000",
                whiteSpace: "pre-wrap",
                textAlign: "left",
                fontSize: 14,
                lineHeight: 1.5,
              }}
            >
              {m.text}
            </span>
          </div>
        ))}
        {loading && (
          <div style={{ textAlign: "left", marginBottom: 12 }}>
            <span
              style={{
                display: "inline-block",
                padding: "10px 14px",
                borderRadius: 12,
                background: "#f1f1f1",
                fontSize: 14,
              }}
            >
              ⏳ Thinking...
            </span>
          </div>
        )}
        <div ref={bottom} />
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask about ABSD, HDB eligibility, stamp duty..."
          style={{
            flex: 1,
            padding: "10px 14px",
            borderRadius: 8,
            border: "1px solid #ddd",
            fontSize: 14,
          }}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          style={{
            padding: "10px 20px",
            borderRadius: 8,
            cursor: loading || !input.trim() ? "not-allowed" : "pointer",
            background: loading || !input.trim() ? "#f0f0f0" : "#0070f3",
            color: loading || !input.trim() ? "#999" : "#fff",
            border: "none",
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
