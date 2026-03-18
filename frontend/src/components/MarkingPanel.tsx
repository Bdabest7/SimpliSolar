import { useState, useEffect } from "react";
import type { Project, Target, MarkType } from "../types";
import { getCoveringImages, imageUrl, computeHeight, getResiduals } from "../api/client";
import type { MarkResidual } from "../api/client";
import { useMarking } from "../hooks/useMarking";
import ImageViewer from "./ImageViewer";

interface Props {
  project: Project;
  target: Target;
  onMeasured: () => void;
}

export default function MarkingPanel({ project, target, onMeasured }: Props) {
  const [coveringImages, setCoveringImages] = useState<string[]>([]);
  const [activeMarkType, setActiveMarkType] = useState<MarkType>("base");
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [residuals, setResiduals] = useState<MarkResidual[]>([]);

  const { markSet, add, clear, refresh } = useMarking(project.id, target.id);

  useEffect(() => {
    refresh();
    getCoveringImages(project.id, target.id)
      .then(setCoveringImages)
      .catch(() => setCoveringImages([]));
  }, [project.id, target.id, refresh]);

  // Re-compute reprojection residuals whenever marks change
  useEffect(() => {
    if (markSet.marks.length === 0) {
      setResiduals([]);
      return;
    }
    getResiduals(project.id, target.id).then(setResiduals);
  }, [markSet.marks, project.id, target.id]);

  const topCount = markSet.marks.filter((m) => m.mark_type === "base").length;
  const tipCount = markSet.marks.filter((m) => m.mark_type === "tip").length;
  const hasDsm = Boolean(project.dsm_path);
  const canCompute = topCount >= 2 && tipCount >= 2 && hasDsm;

  const heightMode = hasDsm ? "DSM" : "No DSM";

  async function handleCompute() {
    setComputing(true);
    setError(null);
    try {
      await computeHeight(project.id, target.id);
      onMeasured();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setComputing(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
      <div className="toolbar">
        <span style={{ fontSize: 13, fontWeight: 500 }}>
          {target.label || target.id}
        </span>
        <button
          className={`mode-btn ${activeMarkType === "base" ? "active-base" : ""}`}
          onClick={() => setActiveMarkType("base")}
          title="Mark the top of the object casting the shadow (e.g. top of fence post)"
        >
          Object Top ({topCount})
        </button>
        <button
          className={`mode-btn ${activeMarkType === "tip" ? "active-tip" : ""}`}
          onClick={() => setActiveMarkType("tip")}
          title="Mark the tip of the shadow on the ground"
        >
          Shadow Tip ({tipCount})
        </button>
        <button onClick={clear}>Clear Marks</button>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: hasDsm ? "var(--text-muted)" : "var(--danger)" }}>
          {hasDsm ? "⛰ DSM height" : "⚠ No DSM — add in project setup"}
        </span>
        <button
          className="primary"
          disabled={!canCompute || computing}
          onClick={handleCompute}
          title={!hasDsm ? "A DSM is required to compute height" : undefined}
        >
          {computing ? "Computing..." : "Compute Height"}
        </button>
        {error && (
          <span style={{ color: "var(--danger)", fontSize: 12 }}>{error}</span>
        )}
      </div>
      <div className="marking-panel">
        {coveringImages.length === 0 ? (
          <div style={{ padding: 40, color: "var(--text-muted)" }}>
            No covering images found. Ensure camera track and images are uploaded.
          </div>
        ) : (
          coveringImages.slice(0, 4).map((name) => (
            <ImageViewer
              key={name}
              imageUrl={imageUrl(project.id, name)}
              imageName={name}
              marks={markSet.marks}
              activeMarkType={activeMarkType}
              onMark={add}
              residuals={residuals}
            />
          ))
        )}
      </div>
    </div>
  );
}
