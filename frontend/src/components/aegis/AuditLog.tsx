import { ShieldAlert, ShieldCheck, ShieldQuestion, Activity } from "lucide-react";
import type { AuditEntry } from "@/lib/aegis-api";

interface Props {
  entries: AuditEntry[];
  connected: boolean;
}

export function AuditLog({ entries, connected }: Props) {
  return (
    <div className="flex h-full flex-col rounded-md border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Activity className="h-3.5 w-3.5 text-primary" />
        <h2 className="text-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Security Audit Stream
        </h2>
        <span className="ml-auto flex items-center gap-1.5 text-mono text-[10px] uppercase tracking-widest">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              connected ? "bg-allow" : "bg-deny"
            } ${connected ? "animate-pulse" : ""}`}
          />
          <span className={connected ? "text-allow" : "text-deny"}>
            {connected ? "live" : "offline"}
          </span>
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {entries.length === 0 ? (
          <div className="p-4 text-mono text-xs text-muted-foreground">
            // No audit events. Stream will populate on intercept.
          </div>
        ) : (
          <ol className="divide-y divide-border">
            {entries.map((e, i) => (
              <li key={`${e.request_id}-${i}`} className="px-3 py-2">
                <Row e={e} />
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function Row({ e }: { e: AuditEntry }) {
  const isDeny = e.decision === "DENY";
  const isQuar = e.decision === "QUARANTINE";
  const Icon = isDeny ? ShieldAlert : isQuar ? ShieldQuestion : ShieldCheck;
  const color = isDeny
    ? "text-deny border-deny/40 bg-deny/5"
    : isQuar
      ? "text-warning border-warning/40 bg-warning/5"
      : "text-allow border-allow/40 bg-allow/5";
  return (
    <div className={`flex gap-2 rounded border-l-2 px-2 py-1.5 ${color}`}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-mono text-[10px] uppercase tracking-widest">
          <span className="font-bold">{e.decision}</span>
          <span className="text-muted-foreground">{e.event_type}</span>
          <span className="ml-auto text-muted-foreground opacity-70">
            {new Date(e.timestamp).toLocaleTimeString()}
          </span>
        </div>
        <div className="mt-0.5 truncate text-mono text-[11px] text-foreground">
          {e.detail || e.violated_rule || e.execution_lifecycle || "—"}
        </div>
        <div className="mt-0.5 flex gap-2 text-mono text-[9px] text-muted-foreground/70">
          <span>req:{e.request_id.slice(0, 8)}</span>
          {e.policy_snapshot_version && <span>pol:{e.policy_snapshot_version}</span>}
        </div>
      </div>
    </div>
  );
}
