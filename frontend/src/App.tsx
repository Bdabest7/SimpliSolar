import { useState, useCallback } from "react";
import type { Project } from "./types";
import { useProject } from "./hooks/useProject";
import ProjectHome from "./components/ProjectHome";
import ProjectSetup from "./components/ProjectSetup";
import TargetList from "./components/TargetList";
import MarkingPanel from "./components/MarkingPanel";
import ResultsTable from "./components/ResultsTable";
import ExportPanel from "./components/ExportPanel";

type Screen = "home" | "setup" | "marking";

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);

  const { project, refresh } = useProject(projectId);

  const handleOpen = useCallback((p: Project) => {
    setProjectId(p.id);
    // Skip setup if the project already has all paths configured
    const fullyConfigured =
      p.status !== "created" &&
      (p.camera_track_path || p.camera_track_file) &&
      p.targets.length > 0 &&
      p.image_dir;
    setScreen(fullyConfigured ? "marking" : "setup");
  }, []);

  const handleProjectReady = useCallback(async (p: Project) => {
    setProjectId(p.id);
    await refresh();
    setScreen("marking");
  }, [refresh]);

  const handleBack = useCallback(() => {
    setProjectId(null);
    setSelectedTargetId(null);
    setScreen("home");
  }, []);

  if (screen === "home") {
    return <ProjectHome onOpen={handleOpen} />;
  }

  // Wait for the project to load from the server before rendering setup/marking
  if (!project) return null;

  if (screen === "setup") {
    return (
      <ProjectSetup
        project={project}
        onProjectReady={handleProjectReady}
        onBack={handleBack}
      />
    );
  }

  const selectedTarget =
    selectedTargetId
      ? project.targets.find((t) => t.id === selectedTargetId) ?? null
      : null;

  return (
    <div className="app">
      <TargetList
        targets={project.targets}
        measurements={project.measurements}
        selectedId={selectedTargetId}
        onSelect={(id) => setSelectedTargetId(id)}
        onHome={handleBack}
      />
      <div className="main-content">
        {selectedTarget ? (
          <MarkingPanel
            project={project}
            target={selectedTarget}
            onMeasured={refresh}
          />
        ) : (
          <div style={{ padding: 40, color: "var(--text-muted)" }}>
            <p>Select a target from the sidebar to begin marking.</p>
            <div style={{ marginTop: 24 }}>
              <ResultsTable measurements={project.measurements} />
              <ExportPanel
                projectId={project.id}
                hasMeasurements={project.measurements.length > 0}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
