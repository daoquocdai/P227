import React, { useState } from "react";
import { Bot, MessageSquare, Send, Sparkles, X, RefreshCw, ShieldAlert, Camera, Users } from "lucide-react";
import { API_BASE_URL } from "../api/client";

interface ChatMessage {
  id: string;
  sender: "user" | "agent";
  text: string;
  timestamp: string;
  data?: any;
}

export default function AgentChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      sender: "agent",
      text: "Xin chào! Tôi là Trợ lý An ninh GuardianCam AI. Bạn có thể hỏi tôi về trạng thái camera, các sự cố té ngã hoặc người lạ gần đây.",
      timestamp: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = query.trim();
    if (!clean || loading) return;

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      sender: "user",
      text: clean,
      timestamp: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setQuery("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: clean }),
      });
      const data = await res.json();

      const agentMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: "agent",
        text: data.answer || "Đã xử lý xong câu hỏi của bạn.",
        timestamp: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
        data: data.data,
      };
      setMessages((prev) => [...prev, agentMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: "agent",
        text: "Không thể kết nối đến AI Agent Server. Vui lòng kiểm tra lại Backend (Port 8000).",
        timestamp: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickQuestion = (qText: string) => {
    setQuery(qText);
  };

  return (
    <>
      {/* Floating Action Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          style={{
            position: "fixed",
            bottom: "24px",
            right: "24px",
            zIndex: 9999,
            backgroundColor: "#2563eb",
            color: "#ffffff",
            border: "none",
            borderRadius: "50px",
            padding: "12px 20px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            boxShadow: "0 8px 24px rgba(37, 99, 235, 0.35)",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "14px",
            transition: "all 0.2s ease",
          }}
        >
          <Sparkles style={{ width: "20px", height: "20px" }} />
          <span>Hỏi AI An Ninh</span>
        </button>
      )}

      {/* Chat Window Modal */}
      {isOpen && (
        <div
          style={{
            position: "fixed",
            bottom: "24px",
            right: "24px",
            width: "380px",
            maxHeight: "580px",
            height: "80vh",
            backgroundColor: "#1e293b",
            color: "#f8fafc",
            borderRadius: "16px",
            boxShadow: "0 12px 36px rgba(0,0,0,0.5)",
            border: "1px solid #334155",
            zIndex: 9999,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            fontFamily: "sans-serif",
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: "14px 16px",
              backgroundColor: "#0f172a",
              borderBottom: "1px solid #334155",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <div
                style={{
                  width: "34px",
                  height: "34px",
                  borderRadius: "50%",
                  backgroundColor: "#2563eb",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Bot style={{ width: "20px", height: "20px", color: "#fff" }} />
              </div>
              <div>
                <strong style={{ fontSize: "15px", display: "block", color: "#f8fafc" }}>
                  GuardianCam AI Assistant
                </strong>
                <span style={{ fontSize: "11px", color: "#94a3b8" }}>Hỗ trợ an ninh & camera 24/7</span>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              style={{
                background: "none",
                border: "none",
                color: "#94a3b8",
                cursor: "pointer",
                padding: "4px",
              }}
            >
              <X style={{ width: "20px", height: "20px" }} />
            </button>
          </div>

          {/* Quick Questions Chips */}
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "#1e293b",
              borderBottom: "1px solid #334155",
              display: "flex",
              gap: "6px",
              overflowX: "auto",
            }}
          >
            <button
              onClick={() => handleQuickQuestion("Hôm nay có sự cố té ngã nào không?")}
              style={{
                fontSize: "11px",
                padding: "4px 8px",
                borderRadius: "12px",
                backgroundColor: "#334155",
                color: "#cbd5e1",
                border: "none",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              ⚠️ Sự cố ngã
            </button>
            <button
              onClick={() => handleQuickQuestion("Trạng thái camera thế nào?")}
              style={{
                fontSize: "11px",
                padding: "4px 8px",
                borderRadius: "12px",
                backgroundColor: "#334155",
                color: "#cbd5e1",
                border: "none",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              📹 Camera
            </button>
            <button
              onClick={() => handleQuickQuestion("Có phát hiện người lạ không?")}
              style={{
                fontSize: "11px",
                padding: "4px 8px",
                borderRadius: "12px",
                backgroundColor: "#334155",
                color: "#cbd5e1",
                border: "none",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              👤 Người lạ
            </button>
          </div>

          {/* Messages Container */}
          <div
            style={{
              flex: 1,
              padding: "14px",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            {messages.map((m) => (
              <div
                key={m.id}
                style={{
                  alignSelf: m.sender === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                }}
              >
                <div
                  style={{
                    backgroundColor: m.sender === "user" ? "#2563eb" : "#334155",
                    color: "#f8fafc",
                    padding: "10px 14px",
                    borderRadius: m.sender === "user" ? "14px 14px 2px 14px" : "14px 14px 14px 2px",
                    fontSize: "13px",
                    lineHeight: "1.6",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {m.text}

                  {/* Render Data Badges if available */}
                  {m.data?.cameras && (
                    <div style={{ marginTop: "8px", fontSize: "11px", color: "#93c5fd" }}>
                      <strong>Các camera:</strong>
                      {m.data.cameras.map((c: any) => (
                        <div key={c.id}>
                          • {c.name} ({c.operational_status})
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <span
                  style={{
                    fontSize: "10px",
                    color: "#64748b",
                    marginTop: "3px",
                    display: "block",
                    textAlign: m.sender === "user" ? "right" : "left",
                  }}
                >
                  {m.timestamp}
                </span>
              </div>
            ))}
            {loading && (
              <div style={{ alignSelf: "flex-start", color: "#94a3b8", fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                <RefreshCw className="spin" style={{ width: "14px", height: "14px" }} />
                <span>AI đang suy luận dữ liệu...</span>
              </div>
            )}
          </div>

          {/* Input Bar */}
          <form
            onSubmit={handleSend}
            style={{
              padding: "10px 12px",
              backgroundColor: "#0f172a",
              borderTop: "1px solid #334155",
              display: "flex",
              gap: "8px",
            }}
          >
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Hỏi AI về sự cố, camera..."
              style={{
                flex: 1,
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
                borderRadius: "8px",
                padding: "8px 12px",
                color: "#f8fafc",
                fontSize: "13px",
                outline: "none",
              }}
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              style={{
                backgroundColor: "#2563eb",
                color: "#ffffff",
                border: "none",
                borderRadius: "8px",
                padding: "8px 12px",
                cursor: loading || !query.trim() ? "not-allowed" : "pointer",
                opacity: loading || !query.trim() ? 0.6 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Send style={{ width: "16px", height: "16px" }} />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
