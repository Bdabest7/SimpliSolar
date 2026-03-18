import type { Target, Measurement } from "../types";

interface Props {
  targets: Target[];
  measurements: Measurement[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onHome?: () => void;
}

export default function TargetList({ targets, measurements, selectedId, onSelect, onHome }: Props) {
  const measMap = new Map(measurements.map((m) => [m.target_id, m]));

  return (
    <div className="sidebar">
      {onHome && (
        <button
          onClick={onHome}
          style={{
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            cursor: "pointer",
            fontSize: 12,
            padding: "0 0 12px 0",
            display: "block",
          }}
        >
          ← Projects
        </button>
      )}
      <div
        className={`target-item ${selectedId === null ? "active" : ""}`}
        style={{ fontSize: 12, opacity: 0.85 }}
        onClick={() => onSelect(null)}
      >
        Results Overview
      </div>
      <h2>Targets ({targets.length})</h2>
      {targets.map((t) => {
        const m = measMap.get(t.id);
        return (
          <div
            key={t.id}
            className={`target-item ${selectedId === t.id ? "active" : ""}`}
            onClick={() => onSelect(selectedId === t.id ? null : t.id)}
          >
            <div className="target-label">
              {t.label || t.id}
              {m && (
                <span style={{ float: "right", fontSize: 12, opacity: 0.8 }}>
                  {m.computed_height.toFixed(3)}m
                </span>
              )}
            </div>
            <div className="target-coords">
              E {t.x.toFixed(2)} &middot; N {t.y.toFixed(2)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
