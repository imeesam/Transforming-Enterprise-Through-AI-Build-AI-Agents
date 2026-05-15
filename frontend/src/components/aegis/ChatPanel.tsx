import { useEffect, useRef, useState } from "react";
import { Send, Terminal } from "lucide-react";

export interface ChatMessage {
  id: string;
  role: "user" | "system" | "agent";
  content: string;
  timestamp: string;
  decision?: "ALLOW" | "DENY" | "QUARANTINE";
}

interface Props {
  messages: ChatMessage[];
  onSend: (prompt: string) => void;
  disabled?: boolean;
  pending?: boolean;
}

export function ChatPanel({ messages, onSend, disabled, pending }: Props) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = input.trim();
    if (!v || disabled) return;
    onSend(v);
    setInput("");
  };

  return (
    <div className="flex h-full flex-col rounded-md border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Terminal className="h-3.5 w-3.5 text-primary" />
        <h2 className="text-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Intent Console
        </h2>
        <span className="ml-auto text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          gemini · isolated
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="text-mono text-xs text-muted-foreground">
            <p className="text-foreground">// Aegis Twin online.</p>
            <p>// Issue an intent. The LLM parses; the deterministic solver computes.</p>
            <p className="mt-2 opacity-60">e.g. "Move end-effector to 120, 60, 0 at slow velocity"</p>
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} m={m} />
        ))}
        {pending && (
          <div className="text-mono text-[11px] text-muted-foreground">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-warning align-middle" />
            <span className="ml-2">Validating intent through proxy…</span>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t border-border p-3">
        <span className="text-mono text-xs text-primary">$</span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={disabled ? "Awaiting authorization…" : "issue intent…"}
          disabled={disabled}
          className="flex-1 bg-transparent text-mono text-sm text-foreground outline-none placeholder:text-muted-foreground/60 disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={disabled || !input.trim()}
          className="inline-flex items-center gap-1.5 rounded border border-border-strong bg-secondary px-3 py-1.5 text-mono text-[11px] uppercase tracking-widest text-foreground transition-colors hover:bg-primary hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-secondary disabled:hover:text-foreground"
        >
          <Send className="h-3 w-3" />
          send
        </button>
      </form>
    </div>
  );
}

function Message({ m }: { m: ChatMessage }) {
  const accent =
    m.role === "user"
      ? "border-primary/40 text-foreground"
      : m.decision === "DENY"
        ? "border-deny/50 text-deny"
        : m.decision === "ALLOW"
          ? "border-allow/40 text-foreground"
          : "border-border text-muted-foreground";
  const tag =
    m.role === "user" ? "OPERATOR" : m.role === "agent" ? "AGENT" : "PROXY";
  return (
    <div className={`rounded border-l-2 ${accent} bg-surface/50 px-3 py-2`}>
      <div className="mb-1 flex items-center gap-2 text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        <span>{tag}</span>
        <span className="opacity-50">{m.timestamp}</span>
        {m.decision && (
          <span
            className={`ml-auto rounded px-1.5 py-0.5 text-[9px] ${
              m.decision === "ALLOW"
                ? "bg-allow/15 text-allow"
                : m.decision === "DENY"
                  ? "bg-deny/15 text-deny"
                  : "bg-warning/15 text-warning"
            }`}
          >
            {m.decision}
          </span>
        )}
      </div>
      <div className="text-mono text-xs leading-relaxed whitespace-pre-wrap">{m.content}</div>
    </div>
  );
}
