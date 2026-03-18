import { useEffect, useState } from "react";
import type { Project } from "../types";
import { listProjects, createProject, deleteProject } from "../api/client";
import ShadowLoader from "./ShadowLoader";

interface Props {
  onOpen: (project: Project) => void;
}

export default function ProjectHome({ onOpen }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listProjects()
      .then((ps) =>
        setProjects(ps.sort((a, b) => b.created_at.localeCompare(a.created_at)))
      )
      .catch(() => setError("Failed to load projects"))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    setError("");
    try {
      const p = await createProject(newName.trim());
      onOpen(p);
    } catch (e: any) {
      setError(`Failed to create project: ${e.message}`);
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;
    await deleteProject(id);
    setProjects((ps) => ps.filter((p) => p.id !== id));
  }

  function statusLabel(p: Project) {
    const t = p.targets.length;
    const m = p.measurements.length;
    if (p.status === "created") return "Setup incomplete";
    if (m > 0) return `${m} / ${t} measured`;
    if (t > 0) return `${t} targets, ready`;
    return "Ingested";
  }

  function statusColor(p: Project) {
    if (p.status === "created") return "var(--text-muted)";
    if (p.measurements.length > 0) return "var(--success)";
    return "var(--warning)";
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return "";
    }
  }

  if (loading) return <ShadowLoader message="Loading projects..." />;

  return (
    <div className="setup-panel">
      <h1>SimpliSolar</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: 32 }}>
        Multi-view shadow engine for sub-centimetre height measurement
      </p>

      {/* New project */}
      <div className="form-group">
        <label>New Project</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Project name"
            style={{ flex: 1 }}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            disabled={creating}
          />
          <button className="primary" onClick={handleCreate} disabled={creating || !newName.trim()}>
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
        {error && (
          <p style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>{error}</p>
        )}
      </div>

      {/* Recent projects */}
      {projects.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 10,
            }}
          >
            Recent Projects
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {projects.map((p) => (
              <div
                key={p.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 14px",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              >
                {/* Name + meta */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: 14,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.name}
                  </div>
                  <div style={{ display: "flex", gap: 12, marginTop: 2, fontSize: 11 }}>
                    <span style={{ color: statusColor(p) }}>{statusLabel(p)}</span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {formatDate(p.created_at)}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <button
                  className="primary"
                  style={{ padding: "4px 14px", fontSize: 13 }}
                  onClick={() => onOpen(p)}
                >
                  Open
                </button>
                <button
                  style={{
                    padding: "4px 10px",
                    fontSize: 13,
                    background: "none",
                    border: "1px solid var(--border)",
                    color: "var(--text-muted)",
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                  onClick={() => handleDelete(p.id, p.name)}
                  title="Delete project"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {projects.length === 0 && !loading && (
        <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 24 }}>
          No projects yet — create one above to get started.
        </p>
      )}
    </div>
  );
}
