import { useState, useEffect, useRef } from "react";
import type { Project, Target, MarkType } from "../types";
import { getCoveringImages, imageUrl, computeHeight, getResiduals, getTargetProjections } from "../api/client";
import type { MarkResidual, TargetProjections } from "../api/client";
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
  const [projections, setProjections] = useState<TargetProjections>({ csv: {}, computed: {} });
  const [sharedZoom, setSharedZoom] = useState<number | null>(null);
  const zoomRafRef = useRef(0);
  const [sliderValue, setSliderValue] = useState(0);

  const { markSet, add, undo, clear, refresh } = useMarking(project.id, target.id);

  useEffect(() => {
    refresh();
    getCoveringImages(project.id, target.id)
      .then(setCoveringImages)
      .catch(() => setCoveringImages([]));
    getTargetProjections(project.id, target.id)
      .then(setProjections)
      .catch(() => setProjections({ csv: {}, computed: {} }));
  }, [project.id, target.id, refresh]);

  // Re-compute reprojection residuals and computed projections whenever marks change
  useEffect(() => {
    if (markSet.marks.length === 0) {
      setResiduals([]);
      setProjections((p) => ({ ...p, computed: {} }));
      return;
    }
    getResiduals(project.id, target.id).then(setResiduals);
    getTargetProjections(project.id, target.id)
      .then(setProjections)
      .catch(() => {});
  }, [markSet.marks, project.id, target.id]);

  const topCount = markSet.marks.filter((m) => m.mark_type === "base").length;
  const tipCount = markSet.marks.filter((m) => m.mark_type === "tip").length;
  const hasDtm = Boolean(project.dtm_path);
  const canCompute = topCount >= 2 && tipCount >= 1 && hasDtm;

  const heightMode = hasDtm ? "DTM" : "No DTM";

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
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", minHeight: 0 }}>
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
        <button
          onClick={undo}
          disabled={markSet.marks.length === 0}
          title="Undo the last mark placed"
        >
          Undo
        </button>
        <button onClick={clear}>Clear Marks</button>
        <span style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: 8 }}>
          <label
            style={{ fontSize: 11, color: "var(--text-muted)", cursor: "pointer", whiteSpace: "nowrap" }}
            title="Zoom all images to the target CSV position. Click label to reset to fit."
            onClick={() => { setSharedZoom(null); setSliderValue(0); }}
          >
            Zoom:
          </label>
          <input
            type="range"
            min={0}
            max={300}
            value={sliderValue}
            onChange={(e) => {
              const v = Number(e.target.value);
              setSliderValue(v);
              cancelAnimationFrame(zoomRafRef.current);
              zoomRafRef.current = requestAnimationFrame(() => {
                setSharedZoom(v === 0 ? null : Math.pow(1.02, v));
              });
            }}
            style={{ width: 90, cursor: "pointer" }}
            title={sharedZoom != null ? `${sharedZoom.toFixed(1)}x` : "Fit"}
          />
          <span style={{ fontSize: 10, color: "var(--text-muted)", minWidth: 28 }}>
            {sharedZoom != null ? `${sharedZoom.toFixed(1)}x` : "Fit"}
          </span>
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: hasDtm ? "var(--text-muted)" : "var(--danger)" }}>
          {hasDtm ? "⛰ DTM height" : "⚠ No DTM — add in project setup"}
        </span>
        <button
          className="primary"
          disabled={!canCompute || computing}
          onClick={handleCompute}
          title={!hasDtm ? "A DTM is required to compute height" : undefined}
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
          coveringImages.map((name) => (
            <ImageViewer
              key={`${target.id}-${name}`}
              imageUrl={imageUrl(project.id, name)}
              imageName={name}
              marks={markSet.marks}
              activeMarkType={activeMarkType}
              onMark={add}
              residuals={residuals}
              csvProjection={projections.csv[name]}
              computedProjection={projections.computed[name]}
              sharedZoom={sharedZoom}
            />
          ))
        )}
      </div>
    </div>
  );
}
