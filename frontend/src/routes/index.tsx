import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Shield, OctagonX, RotateCcw } from "lucide-react";
import { ArmVisualizer } from "@/components/aegis/ArmVisualizer";
import { ChatPanel, type ChatMessage } from "@/components/aegis/ChatPanel";
import { AuditLog } from "@/components/aegis/AuditLog";
import { PreviewBanner } from "@/components/aegis/PreviewBanner";
import {
  aegisApi,
  type AuditEntry,
  type JointAngles,
  type PreviewResponse,
  AEGIS_API_BASE,
} from "@/lib/aegis-api";

export const Route = createFileRoute("/")({
  component: AegisDashboard,
});

type FsmState =
  | "IDLE"
  | "PLANNING"
  | "VALIDATING"
  | "PREVIEW"
  | "EXECUTING"
  | "BLOCKED"
  | "EMERGENCY_STOP"
  | "ROLLBACK_PENDING";

const uid = () => Math.random().toString(36).slice(2, 10);
const now = () => new Date().toLocaleTimeString();

function AegisDashboard() {
  const [fsm, setFsm] = useState<FsmState>("IDLE");
  const [joints, setJoints] = useState<JointAngles>({ j1: 30, j2: -45, j3: -30 });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [executing, setExecuting] = useState<PreviewResponse["trajectory"] | null>(null);
  const [pending, setPending] = useState(false);
  const [connected, setConnected] = useState(false);
  const auditSeen = useRef<Set<string>>(new Set());

  const pushMsg = (m: Omit<ChatMessage, "id" | "timestamp">) =>
    setMessages((s) => [...s, { ...m, id: uid(), timestamp: now() }]);

  const pushAudit = (e: AuditEntry) => {
    const key = `${e.request_id}-${e.timestamp}-${e.event_type}`;
    if (auditSeen.current.has(key)) return;
    auditSeen.current.add(key);
    setAudit((s) => [e, ...s].slice(0, 200));
  };

  // Poll backend for connectivity, audit log and robot state
  useEffect(() => {
    let stopped = false;
    const poll = async () => {
      try {
        const [log, state] = await Promise.all([
          aegisApi.getAuditLog().catch(() => null),
          aegisApi.getRobotState().catch(() => null),
        ]);
        if (stopped) return;
        if (log) {
          setConnected(true);
          for (const e of log) pushAudit(e);
        } else {
          setConnected(false);
        }
        if (state?.joints && fsm !== "EXECUTING") setJoints(state.joints);
      } catch {
        if (!stopped) setConnected(false);
      }
    };
    poll();
    const i = window.setInterval(poll, 2500);
    return () => {
      stopped = true;
      window.clearInterval(i);
    };
  }, [fsm]);

  const handleSend = useCallback(async (prompt: string) => {
    if (fsm === "EMERGENCY_STOP") return;
    pushMsg({ role: "user", content: prompt });
    setPending(true);
    setFsm("PLANNING");

    // Optimistic local audit until backend response
    const reqId = uid();
    pushAudit({
      request_id: reqId,
      timestamp: new Date().toISOString(),
      event_type: "PROMPT",
      decision: "ALLOW",
      detail: `Intent received: "${prompt.slice(0, 60)}"`,
    });

    try {
      setFsm("VALIDATING");
      const intent = await aegisApi.parseIntent(prompt);
      const { x, y, z } = intent.target_coordinates;
      pushAudit({
        request_id: reqId,
        timestamp: new Date().toISOString(),
        event_type: "TOOL_CALL",
        decision: "ALLOW",
        detail: `Intent parsed → x=${x}, y=${y}, z=${z}`,
      });
      const res = await aegisApi.previewTrajectory({ x, y, z });
      pushAudit({
        request_id: res.request_id || reqId,
        timestamp: new Date().toISOString(),
        event_type: "TOOL_CALL",
        decision: res.decision,
        policy_snapshot_version: res.policy_snapshot_version,
        violated_rule: res.violated_rule,
        detail:
          res.decision === "ALLOW"
            ? `Trajectory ${res.trajectory_id.slice(0, 8)} staged (${res.trajectory.length} pts)`
            : `Blocked by ${res.violated_rule || "policy"}`,
      });

      if (res.decision !== "ALLOW") {
        setFsm("BLOCKED");
        pushMsg({
          role: "system",
          decision: res.decision,
          content: `Proxy ${res.decision}: ${res.violated_rule || res.message || "policy violation"}`,
        });
        setTimeout(() => setFsm("IDLE"), 1500);
        return;
      }

      setPreview(res);
      setFsm("PREVIEW");
      pushMsg({
        role: "agent",
        decision: "ALLOW",
        content: `Trajectory staged. ${res.trajectory.length} waypoints. Awaiting your confirmation.`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      pushAudit({
        request_id: reqId,
        timestamp: new Date().toISOString(),
        event_type: "TOOL_CALL",
        decision: "DENY",
        detail: `Backend unreachable: ${msg.slice(0, 80)}`,
      });
      pushMsg({
        role: "system",
        decision: "DENY",
        content: `Backend error at ${AEGIS_API_BASE}: ${msg}`,
      });
      setFsm("IDLE");
    } finally {
      setPending(false);
    }
  }, [fsm]);

  const handleConfirm = useCallback(async () => {
    if (!preview) return;
    const traj = preview.trajectory;
    setFsm("EXECUTING");
    setExecuting(traj);
    pushAudit({
      request_id: preview.request_id,
      timestamp: new Date().toISOString(),
      event_type: "CONFIRMATION",
      decision: "ALLOW",
      policy_snapshot_version: preview.policy_snapshot_version,
      detail: `Operator confirmed ${preview.trajectory_id.slice(0, 8)}`,
    });
    pushMsg({ role: "agent", decision: "ALLOW", content: "Execution confirmed. Mutating sim state." });
    try {
      await aegisApi.confirmExecution(preview.trajectory_id);
    } catch {
      // continue local animation regardless
    }
    setPreview(null);
    // settle to final after animation
    const totalMs = traj.length * 40 + 200;
    window.setTimeout(() => {
      setJoints(traj[traj.length - 1]);
      setExecuting(null);
      setFsm("IDLE");
      pushAudit({
        request_id: preview.request_id,
        timestamp: new Date().toISOString(),
        event_type: "STATE_CHANGE",
        decision: "ALLOW",
        execution_lifecycle: "COMPLETED",
        detail: "Execution complete · IDLE",
      });
    }, totalMs);
  }, [preview]);

  const handleCancel = useCallback(async () => {
    if (!preview) return;
    setFsm("ROLLBACK_PENDING");
    pushAudit({
      request_id: preview.request_id,
      timestamp: new Date().toISOString(),
      event_type: "STATE_CHANGE",
      decision: "DENY",
      detail: "Operator cancelled preview · rollback",
    });
    pushMsg({ role: "system", decision: "DENY", content: "Trajectory cancelled. Rolling back." });
    try {
      await aegisApi.cancelExecution(preview.trajectory_id);
    } catch {
      /* noop */
    }
    setPreview(null);
    window.setTimeout(() => setFsm("IDLE"), 600);
  }, [preview]);

  const handleEStop = useCallback(async () => {
    setFsm("EMERGENCY_STOP");
    setPreview(null);
    setExecuting(null);
    pushAudit({
      request_id: uid(),
      timestamp: new Date().toISOString(),
      event_type: "STATE_CHANGE",
      decision: "DENY",
      detail: "EMERGENCY_STOP engaged · controls locked",
    });
    pushMsg({ role: "system", decision: "DENY", content: "E-STOP engaged. All execution halted." });
    try {
      await aegisApi.emergencyStop();
    } catch {
      /* noop */
    }
  }, []);

  const handleReset = useCallback(() => {
    setFsm("IDLE");
    pushAudit({
      request_id: uid(),
      timestamp: new Date().toISOString(),
      event_type: "STATE_CHANGE",
      decision: "ALLOW",
      detail: "Admin reset · SAFE_IDLE → IDLE",
    });
  }, []);

  const isLocked = fsm === "EMERGENCY_STOP" || fsm === "PREVIEW" || fsm === "EXECUTING" || pending;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header
        fsm={fsm}
        connected={connected}
        onEStop={handleEStop}
        onReset={handleReset}
        estop={fsm === "EMERGENCY_STOP"}
      />

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 p-3 lg:p-4">
        {preview && fsm === "PREVIEW" && (
          <PreviewBanner
            trajectoryId={preview.trajectory_id}
            policySnapshot={preview.policy_snapshot_version}
            target={preview.target}
            pointCount={preview.trajectory.length}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        )}

        <div className="grid flex-1 gap-3 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)_minmax(0,360px)]">
          <div className="min-h-[420px] lg:min-h-0">
            <ChatPanel
              messages={messages}
              onSend={handleSend}
              disabled={isLocked}
              pending={pending}
            />
          </div>

          <div className="min-h-[420px] lg:min-h-0">
            <ArmVisualizer
              current={joints}
              preview={preview?.trajectory}
              executing={executing}
              estop={fsm === "EMERGENCY_STOP"}
              fsmState={fsm}
            />
          </div>

          <div className="min-h-[420px] lg:min-h-0">
            <AuditLog entries={audit} connected={connected} />
          </div>
        </div>

        <Footer />
      </main>
    </div>
  );
}

function Header({
  fsm,
  connected,
  onEStop,
  onReset,
  estop,
}: {
  fsm: FsmState;
  connected: boolean;
  onEStop: () => void;
  onReset: () => void;
  estop: boolean;
}) {
  const stateColor =
    fsm === "EMERGENCY_STOP" || fsm === "BLOCKED"
      ? "text-deny border-deny/40 bg-deny/10"
      : fsm === "PREVIEW" || fsm === "VALIDATING" || fsm === "PLANNING" || fsm === "ROLLBACK_PENDING"
        ? "text-warning border-warning/40 bg-warning/10 animate-pulse-ring"
        : fsm === "EXECUTING"
          ? "text-primary border-primary/40 bg-primary/10"
          : "text-allow border-allow/40 bg-allow/10";

  return (
    <header className="border-b border-border bg-surface/60 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1600px] items-center gap-4 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded border border-primary/40 bg-primary/10">
            <Shield className="h-4 w-4 text-primary" />
          </div>
          <div className="flex flex-col leading-tight">
            <h1 className="text-mono text-sm font-bold uppercase tracking-[0.2em] text-foreground">
              Aegis Twin
            </h1>
            <span className="text-mono text-[9px] uppercase tracking-[0.25em] text-muted-foreground">
              cyber-physical safety console · mvp
            </span>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-2 rounded border px-2.5 py-1 text-mono text-[10px] uppercase tracking-widest ${stateColor}`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            FSM · {fsm}
          </span>
          <span className="text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            proxy · {connected ? <span className="text-allow">connected</span> : <span className="text-deny">offline</span>}
          </span>

          {estop ? (
            <button
              onClick={onReset}
              className="inline-flex items-center gap-1.5 rounded border border-warning/60 bg-warning/10 px-3 py-1.5 text-mono text-[10px] font-bold uppercase tracking-widest text-warning transition-colors hover:bg-warning hover:text-warning-foreground"
            >
              <RotateCcw className="h-3 w-3" />
              Admin Reset
            </button>
          ) : (
            <button
              onClick={onEStop}
              className="inline-flex items-center gap-1.5 rounded border border-deny/60 bg-deny/10 px-3 py-1.5 text-mono text-[10px] font-bold uppercase tracking-widest text-deny transition-colors hover:bg-deny hover:text-deny-foreground"
            >
              <OctagonX className="h-3 w-3" />
              E-Stop
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="flex items-center justify-between gap-4 border-t border-border pt-2 text-mono text-[9px] uppercase tracking-widest text-muted-foreground">
      <span>backend · {AEGIS_API_BASE}</span>
      <span>zero-trust · deterministic kinematics · capability isolation</span>
      <span>policy snapshot · v1.3.2</span>
    </footer>
  );
}
