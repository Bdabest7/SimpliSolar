import { useState, useEffect } from "react";
import type { Project } from "../types";
import { linkCameraTrack, linkTargets, linkImages, linkDsm, browseFile, browseDirectory, getProjectCrsInfo } from "../api/client";
import ShadowLoader from "./ShadowLoader";

interface Props {
  project: Project;
  onProjectReady: (project: Project) => void;
  onBack: () => void;
}

type StepStatus = "idle" | "running" | "done" | "error";

interface StepState {
  status: StepStatus;
  detail: string;
}

const IDLE: StepState = { status: "idle", detail: "" };

export default function ProjectSetup({ project: initialProject, onProjectReady, onBack }: Props) {
  const [project, setProject] = useState<Project>(initialProject);
  const [format, setFormat] = useState(initialProject.camera_track_format || "pix4dmatic");

  // Path inputs
  const [cameraPath, setCameraPath] = useState(initialProject.camera_track_path || "");
  const [targetsPath, setTargetsPath] = useState(initialProject.target_csv || "");
  const [imagesPath, setImagesPath] = useState(
    initialProject.image_dir && initialProject.image_dir !== "images"
      ? initialProject.image_dir
      : ""
  );
  const [dsmPath, setDsmPath] = useState(initialProject.dsm_path || "");

  // Target CSV options
  const [csvLayout, setCsvLayout] = useState("auto");
  const [csvEpsg, setCsvEpsg] = useState("");

  // CRS info from camera track
  const [crsInfo, setCrsInfo] = useState<{ name: string | null; epsg: string | null } | null>(null);

  // Per-step status
  const [cameraStep, setCameraStep] = useState<StepState>(
    initialProject.camera_track_path ? { status: "done", detail: "Previously linked" } : IDLE
  );
  const [targetsStep, setTargetsStep] = useState<StepState>(
    initialProject.target_csv ? { status: "done", detail: `${initialProject.targets.length} targets` } : IDLE
  );
  const [imagesStep, setImagesStep] = useState<StepState>(
    initialProject.image_dir && initialProject.image_dir !== "images"
      ? { status: "done", detail: "Previously linked" }
      : IDLE
  );
  const [dsmStep, setDsmStep] = useState<StepState>(
    initialProject.dsm_path ? { status: "done", detail: "Previously linked" } : IDLE
  );

  const [log, setLog] = useState<string[]>([]);

  // Load CRS info once the camera track is linked
  useEffect(() => {
    if (cameraStep.status === "done") {
      getProjectCrsInfo(project.id)
        .then((info) => setCrsInfo(info))
        .catch(() => {});
    }
  }, [cameraStep.status, project.id]);

  function addLog(msg: string) {
    const ts = new Date().toLocaleTimeString();
    setLog((prev) => [...prev, `[${ts}] ${msg}`]);
  }

  const busy =
    cameraStep.status === "running" ||
    targetsStep.status === "running" ||
    imagesStep.status === "running" ||
    dsmStep.status === "running";

  async function applyCamera() {
    if (!cameraPath.trim()) return;
    setCameraStep({ status: "running", detail: "Validating..." });
    addLog(`Linking camera track (${format}): ${cameraPath}`);
    try {
      const p = await linkCameraTrack(project.id, cameraPath.trim(), format);
      setProject(p);
      setCameraStep({ status: "done", detail: `${format} — linked OK` });
      addLog("Camera track linked successfully");
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      setCameraStep({ status: "error", detail: msg });
      addLog(`ERROR: ${msg}`);
    }
  }

  async function applyTargets() {
    if (!targetsPath.trim()) return;
    setTargetsStep({ status: "running", detail: "Parsing CSV..." });
    addLog(`Linking targets CSV: ${targetsPath}  layout=${csvLayout}${csvEpsg ? "  epsg=" + csvEpsg : ""}`);
    try {
      const result = await linkTargets(project.id, targetsPath.trim(), csvLayout, csvEpsg);
      setProject(result.project);
      const n = result.project.targets.length;
      if (result.warning) {
        setTargetsStep({ status: "done", detail: `${n} targets — ⚠ see log` });
        result.warning.split("\n").forEach((w) => addLog(`⚠ ${w}`));
      } else {
        setTargetsStep({ status: "done", detail: `${n} targets loaded` });
        addLog(`Targets linked: ${n} targets`);
      }
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      setTargetsStep({ status: "error", detail: msg });
      addLog(`ERROR: ${msg}`);
    }
  }

  async function applyImages() {
    if (!imagesPath.trim()) return;
    setImagesStep({ status: "running", detail: "Scanning directory..." });
    addLog(`Linking images directory: ${imagesPath}`);
    try {
      const result = await linkImages(project.id, imagesPath.trim());
      setProject(result.project as Project);
      setImagesStep({ status: "done", detail: `${result.count} images found` });
      addLog(`Images linked: ${result.count} images`);
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      setImagesStep({ status: "error", detail: msg });
      addLog(`ERROR: ${msg}`);
    }
  }

  async function applyDsm() {
    if (!dsmPath.trim()) return;
    setDsmStep({ status: "running", detail: "Validating DSM..." });
    addLog(`Linking DSM: ${dsmPath}`);
    try {
      const p = await linkDsm(project.id, dsmPath.trim());
      setProject(p);
      setDsmStep({ status: "done", detail: "DSM linked — using DSM height mode" });
      addLog("DSM linked successfully");
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      setDsmStep({ status: "error", detail: msg });
      addLog(`ERROR: ${msg}`);
    }
  }

  const allDone =
    cameraStep.status === "done" &&
    targetsStep.status === "done" &&
    imagesStep.status === "done" &&
    dsmStep.status === "done";

  function cameraPathLabel() {
    if (format === "pix4dmatic") return "OPF directory path";
    if (format === "metashape") return "cameras.xml file path";
    return "External params (.txt) file path";
  }

  function cameraPathHint() {
    if (format === "pix4dmatic")
      return "Paste the full path to the OPF folder (the one containing calibrated_cameras.json).";
    if (format === "metashape")
      return "Paste the full path to your Metashape cameras.xml export.";
    return "Paste the full path to the external camera parameters .txt file.";
  }

  return (
    <div className="setup-panel">
      {busy && <ShadowLoader message="Linking files..." />}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
        <button
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            cursor: "pointer",
            fontSize: 13,
            padding: 0,
          }}
        >
          ← Projects
        </button>
        <h1 style={{ margin: 0 }}>{project.name}</h1>
      </div>
      <p style={{ color: "var(--text-muted)", marginBottom: 28 }}>
        Point SimpliSolar to your existing files. Nothing is copied — files stay where they are.
      </p>

      {/* ── Camera Track ── */}
      <Section label="Camera Track">
        <div className="form-group" style={{ marginBottom: 8 }}>
          <label>Format</label>
          <select
            value={format}
            onChange={(e) => {
              setFormat(e.target.value);
              setCameraStep(IDLE);
            }}
            disabled={busy}
          >
            <option value="pix4dmatic">Pix4DMatic (OPF)</option>
            <option value="metashape">Metashape (cameras.xml)</option>
            <option value="pix4d">Pix4DMapper (.txt/.cam)</option>
          </select>
        </div>
        <PathInput
          label={cameraPathLabel()}
          hint={cameraPathHint()}
          value={cameraPath}
          onChange={setCameraPath}
          onApply={applyCamera}
          onBrowse={async () => {
            const p = format === "pix4dmatic"
              ? await browseDirectory("Select OPF Directory")
              : await browseFile(
                  format === "metashape" ? "Select cameras.xml" : "Select external params .txt",
                  format === "metashape" ? "xml" : "txt"
                );
            if (p) { setCameraPath(p); setCameraStep(IDLE); }
          }}
          step={cameraStep}
          disabled={busy}
        />
      </Section>

      {/* ── Target Coordinates ── */}
      <Section label="Target Coordinates">
        {/* CRS info from camera track */}
        {crsInfo?.name && (
          <div style={{
            fontSize: 11, marginBottom: 10, padding: "6px 8px",
            background: "var(--bg)", borderRadius: 5,
            border: "1px solid var(--border)", color: "var(--text-muted)",
          }}>
            <strong>Camera CRS:</strong> {crsInfo.name}
            {crsInfo.epsg && <span> (EPSG:{crsInfo.epsg})</span>}
          </div>
        )}

        {/* Layout + EPSG row */}
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 11, display: "block", marginBottom: 3 }}>Column layout</label>
            <select
              value={csvLayout}
              onChange={(e) => { setCsvLayout(e.target.value); setTargetsStep(IDLE); }}
              disabled={busy}
              style={{ width: "100%" }}
            >
              <option value="auto">Auto-detect (by column name)</option>
              <option value="swap_xy">Auto-detect + swap X↔Y</option>
              <option value="penz">PENZ — ID, Easting, Northing, Z</option>
              <option value="pnez">PNEZ — ID, Northing, Easting, Z</option>
              <option value="xyz">XYZ — ID, X(Easting), Y(Northing), Z</option>
              <option value="yxz">YXZ — ID, Y(Northing), X(Easting), Z</option>
            </select>
          </div>
          <div style={{ width: 120 }}>
            <label style={{ fontSize: 11, display: "block", marginBottom: 3 }}>
              CSV EPSG <span style={{ color: "var(--text-muted)" }}>(optional)</span>
            </label>
            <input
              value={csvEpsg}
              onChange={(e) => setCsvEpsg(e.target.value)}
              placeholder="e.g. 6575"
              disabled={busy}
              style={{ width: "100%", fontFamily: "monospace" }}
            />
          </div>
        </div>

        <PathInput
          label="CSV file"
          hint="Coordinates must be in the same CRS as your photogrammetry project."
          value={targetsPath}
          onChange={setTargetsPath}
          onApply={applyTargets}
          onBrowse={async () => {
            const p = await browseFile("Select Target Coordinates CSV", "csv");
            if (p) { setTargetsPath(p); setTargetsStep(IDLE); }
          }}
          step={targetsStep}
          disabled={busy}
        />
      </Section>

      {/* ── Images ── */}
      <Section label="Drone Images">
        <PathInput
          label="Images folder"
          hint="Folder containing your drone images (.jpg / .tif)."
          value={imagesPath}
          onChange={setImagesPath}
          onApply={applyImages}
          onBrowse={async () => {
            const p = await browseDirectory("Select Images Folder");
            if (p) { setImagesPath(p); setImagesStep(IDLE); }
          }}
          step={imagesStep}
          disabled={busy}
        />
      </Section>

      {/* ── DSM (required) ── */}
      <Section label="Ground Elevation Model">
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10, marginTop: 0 }}>
          Required. Height is computed as Object Top elevation minus DSM ground elevation at that XY.
          The DSM must be in the same projected CRS as your camera track (check CRS info above).
        </p>
        <PathInput
          label="DSM/DTM GeoTIFF (.tif)"
          hint="Must cover the project area and match the camera track CRS."
          value={dsmPath}
          onChange={setDsmPath}
          onApply={applyDsm}
          onBrowse={async () => {
            const p = await browseFile("Select DSM/DTM GeoTIFF", "tif");
            if (p) { setDsmPath(p); setDsmStep(IDLE); }
          }}
          step={dsmStep}
          disabled={busy}
        />
      </Section>

      {/* ── Continue ── */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8 }}>
        <button
          className="primary"
          disabled={!allDone || busy}
          onClick={() => onProjectReady(project)}
        >
          Continue to Marking →
        </button>
        {!allDone && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Apply all four sections above
          </span>
        )}
      </div>

      {/* ── Log ── */}
      {log.length > 0 && (
        <details style={{ marginTop: 20 }}>
          <summary
            style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer", userSelect: "none" }}
          >
            Import log ({log.length} entries)
          </summary>
          <div
            style={{
              marginTop: 6,
              padding: 10,
              background: "var(--bg)",
              borderRadius: 6,
              border: "1px solid var(--border)",
              maxHeight: 180,
              overflowY: "auto",
              fontSize: 11,
              fontFamily: "monospace",
              lineHeight: 1.6,
            }}
          >
            {log.map((line, i) => (
              <div
                key={i}
                style={{ color: line.includes("ERROR") ? "var(--danger)" : "var(--text-muted)" }}
              >
                {line}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        marginBottom: 24,
        padding: "14px 16px",
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 12,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

interface PathInputProps {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  onApply: () => void;
  onBrowse: () => Promise<void>;
  step: { status: string; detail: string };
  disabled: boolean;
}

function PathInput({ label, hint, value, onChange, onApply, onBrowse, step, disabled }: PathInputProps) {
  const [browsing, setBrowsing] = useState(false);

  const statusColor =
    step.status === "done" ? "var(--success)" :
    step.status === "error" ? "var(--danger)" :
    step.status === "running" ? "var(--warning)" :
    "var(--text-muted)";

  const statusIcon =
    step.status === "done" ? "✓" :
    step.status === "error" ? "✗" :
    step.status === "running" ? "…" : "";

  async function handleBrowse() {
    setBrowsing(true);
    try { await onBrowse(); }
    finally { setBrowsing(false); }
  }

  return (
    <div className="form-group" style={{ marginBottom: 0 }}>
      <label>{label}</label>
      <div style={{ display: "flex", gap: 6, alignItems: "stretch" }}>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Click Browse or paste a path"
          style={{ flex: 1, fontFamily: "monospace", fontSize: 12 }}
          disabled={disabled || browsing}
          onKeyDown={(e) => e.key === "Enter" && onApply()}
        />
        <button
          onClick={handleBrowse}
          disabled={disabled || browsing}
          style={{ whiteSpace: "nowrap" }}
          title="Open file browser"
        >
          {browsing ? "…" : "Browse"}
        </button>
        <button
          onClick={onApply}
          disabled={disabled || browsing || !value.trim()}
          style={{ whiteSpace: "nowrap" }}
          className="primary"
        >
          Apply
        </button>
      </div>
      <div style={{ marginTop: 4, fontSize: 11 }}>
        {step.status !== "idle" ? (
          <span style={{ color: statusColor, fontWeight: 600 }}>
            {statusIcon} {step.detail}
          </span>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>{hint}</span>
        )}
      </div>
    </div>
  );
}
