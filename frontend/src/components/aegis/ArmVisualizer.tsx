import { useEffect, useMemo, useRef, useState } from "react";
import type { JointAngles, TrajectoryPoint } from "@/lib/aegis-api";

interface Props {
  current: JointAngles;
  preview?: TrajectoryPoint[] | null;
  executing?: TrajectoryPoint[] | null;
  estop?: boolean;
  fsmState: string;
}

const L1 = 110;
const L2 = 95;
const L3 = 70;

function forwardKinematics(j: JointAngles) {
  const a1 = (j.j1 * Math.PI) / 180;
  const a2 = a1 + (j.j2 * Math.PI) / 180;
  const a3 = a2 + (j.j3 * Math.PI) / 180;
  const p0 = { x: 0, y: 0 };
  const p1 = { x: p0.x + L1 * Math.cos(a1), y: p0.y + L1 * Math.sin(a1) };
  const p2 = { x: p1.x + L2 * Math.cos(a2), y: p1.y + L2 * Math.sin(a2) };
  const p3 = { x: p2.x + L3 * Math.cos(a3), y: p2.y + L3 * Math.sin(a3) };
  return [p0, p1, p2, p3];
}

export function ArmVisualizer({ current, preview, executing, estop, fsmState }: Props) {
  const [animIndex, setAnimIndex] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!executing || executing.length === 0) {
      setAnimIndex(0);
      return;
    }
    let i = 0;
    const tick = () => {
      i += 1;
      setAnimIndex(i);
      if (i < executing.length - 1) {
        rafRef.current = window.setTimeout(tick, 40) as unknown as number;
      }
    };
    rafRef.current = window.setTimeout(tick, 40) as unknown as number;
    return () => {
      if (rafRef.current) clearTimeout(rafRef.current);
    };
  }, [executing]);

  const liveJoints = executing && executing[animIndex] ? executing[animIndex] : current;
  const livePts = useMemo(() => forwardKinematics(liveJoints), [liveJoints]);

  const ghostPts = preview && preview.length > 0
    ? forwardKinematics(preview[preview.length - 1])
    : null;

  const previewPath = useMemo(() => {
    if (!preview || preview.length === 0) return "";
    return preview
      .map((p, i) => {
        const pts = forwardKinematics(p);
        const ee = pts[3];
        return `${i === 0 ? "M" : "L"} ${ee.x.toFixed(1)} ${ee.y.toFixed(1)}`;
      })
      .join(" ");
  }, [preview]);

  // SVG coordinates: invert Y, center origin
  return (
    <div className="relative h-full w-full overflow-hidden rounded-md border border-border bg-surface">
      <svg
        viewBox="-200 -250 400 320"
        className="h-full w-full"
        style={{ transform: "scaleY(-1)" }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Grid */}
        <defs>
          <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--color-grid)" strokeWidth="0.5" />
          </pattern>
          <pattern id="gridMajor" width="100" height="100" patternUnits="userSpaceOnUse">
            <path d="M 100 0 L 0 0 0 100" fill="none" stroke="var(--color-border-strong)" strokeWidth="0.8" />
          </pattern>
        </defs>
        <rect x="-200" y="-250" width="400" height="320" fill="url(#grid)" />
        <rect x="-200" y="-250" width="400" height="320" fill="url(#gridMajor)" />

        {/* Workspace bounds */}
        <circle cx="0" cy="0" r={L1 + L2 + L3} fill="none" stroke="var(--color-primary)" strokeOpacity="0.15" strokeDasharray="3 4" />

        {/* Floor line */}
        <line x1="-200" y1="0" x2="200" y2="0" stroke="var(--color-border-strong)" strokeWidth="1" />

        {/* Preview trajectory path */}
        {previewPath && (
          <path
            d={previewPath}
            fill="none"
            stroke="var(--color-warning)"
            strokeWidth="1.5"
            strokeDasharray="4 4"
            className="animate-dash"
            opacity="0.9"
          />
        )}

        {/* Ghost arm */}
        {ghostPts && (
          <g opacity="0.35">
            {ghostPts.slice(0, -1).map((p, i) => {
              const n = ghostPts[i + 1];
              return (
                <line
                  key={i}
                  x1={p.x}
                  y1={p.y}
                  x2={n.x}
                  y2={n.y}
                  stroke="var(--color-warning)"
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray="3 3"
                />
              );
            })}
            <circle cx={ghostPts[3].x} cy={ghostPts[3].y} r="6" fill="var(--color-warning)" />
          </g>
        )}

        {/* Live arm */}
        {livePts.slice(0, -1).map((p, i) => {
          const n = livePts[i + 1];
          return (
            <line
              key={i}
              x1={p.x}
              y1={p.y}
              x2={n.x}
              y2={n.y}
              stroke={estop ? "var(--color-deny)" : "var(--color-primary)"}
              strokeWidth="7"
              strokeLinecap="round"
            />
          );
        })}

        {/* Joints */}
        {livePts.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={i === 0 ? 8 : i === livePts.length - 1 ? 5 : 5}
            fill={estop ? "var(--color-deny)" : "var(--color-background)"}
            stroke={estop ? "var(--color-deny)" : "var(--color-primary)"}
            strokeWidth="2"
          />
        ))}
      </svg>

      {/* HUD overlay */}
      <div className="pointer-events-none absolute inset-0 bg-scanlines opacity-30" />
      <div className="absolute left-3 top-3 flex flex-col gap-1 text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        <span>AEGIS // 3-DOF PLANAR</span>
        <span>STATE: <span className="text-foreground">{fsmState}</span></span>
      </div>
      <div className="absolute right-3 top-3 text-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        <div>J1 {liveJoints.j1.toFixed(1)}°</div>
        <div>J2 {liveJoints.j2.toFixed(1)}°</div>
        <div>J3 {liveJoints.j3.toFixed(1)}°</div>
      </div>
      {estop && (
        <div className="absolute inset-0 flex items-center justify-center bg-deny/10 backdrop-blur-[1px]">
          <div className="rounded-md border border-deny bg-background/80 px-6 py-3 text-mono text-sm font-bold uppercase tracking-widest text-deny animate-pulse">
            EMERGENCY STOP ENGAGED
          </div>
        </div>
      )}
    </div>
  );
}
