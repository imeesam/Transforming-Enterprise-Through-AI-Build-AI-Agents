import { useEffect, useState } from "react";
import { Check, X, AlertTriangle } from "lucide-react";

interface Props {
  trajectoryId: string;
  policySnapshot?: string;
  target?: { x: number; y: number; z: number };
  pointCount: number;
  onConfirm: () => void;
  onCancel: () => void;
  timeoutSeconds?: number;
}

export function PreviewBanner({
  trajectoryId,
  policySnapshot,
  target,
  pointCount,
  onConfirm,
  onCancel,
  timeoutSeconds = 30,
}: Props) {
  const [remaining, setRemaining] = useState(timeoutSeconds);
  useEffect(() => {
    setRemaining(timeoutSeconds);
    const i = window.setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          window.clearInterval(i);
          onCancel();
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => window.clearInterval(i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trajectoryId]);

  const pct = (remaining / timeoutSeconds) * 100;

  return (
    <div className="rounded-md border border-warning/60 bg-warning/5 panel-glow">
      <div className="flex items-center gap-3 border-b border-warning/30 px-4 py-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-warning opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-warning" />
        </span>
        <AlertTriangle className="h-4 w-4 text-warning" />
        <span className="text-mono text-[11px] font-bold uppercase tracking-widest text-warning">
          Preview · Awaiting Operator Confirmation
        </span>
        <span className="ml-auto text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          auto-rollback in <span className="text-warning">{remaining}s</span>
        </span>
      </div>
      <div className="grid gap-4 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-mono text-[11px] sm:grid-cols-4">
          <Field label="trajectory_id" value={trajectoryId.slice(0, 12) + "…"} />
          <Field label="policy" value={policySnapshot || "v—"} />
          <Field label="waypoints" value={String(pointCount)} />
          <Field
            label="target"
            value={
              target
                ? `${target.x.toFixed(0)},${target.y.toFixed(0)},${target.z.toFixed(0)}`
                : "—"
            }
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="inline-flex items-center gap-1.5 rounded border border-deny/60 bg-deny/10 px-4 py-2 text-mono text-[11px] font-bold uppercase tracking-widest text-deny transition-colors hover:bg-deny hover:text-deny-foreground"
          >
            <X className="h-3.5 w-3.5" />
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="inline-flex items-center gap-1.5 rounded border border-allow/60 bg-allow/10 px-4 py-2 text-mono text-[11px] font-bold uppercase tracking-widest text-allow transition-colors hover:bg-allow hover:text-allow-foreground"
          >
            <Check className="h-3.5 w-3.5" />
            Confirm Execute
          </button>
        </div>
      </div>
      <div className="h-0.5 w-full overflow-hidden bg-warning/15">
        <div
          className="h-full bg-warning transition-[width] duration-1000 ease-linear"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}
