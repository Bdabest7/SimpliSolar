/** Typed API client for the SimpliSolar backend. */

import type { Project, MarkSet, ImageMark, Measurement } from "../types";

const BASE = "/api";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API error ${response.status}: ${text}`);
  }
  return response.json();
}

// --- Projects ---

export async function listProjects(): Promise<Project[]> {
  return json(await fetch(`${BASE}/projects/`));
}

export async function createProject(name: string): Promise<Project> {
  const form = new FormData();
  form.append("name", name);
  return json(await fetch(`${BASE}/projects/`, { method: "POST", body: form }));
}

export async function getProject(id: string): Promise<Project> {
  return json(await fetch(`${BASE}/projects/${id}`));
}

export async function deleteProject(id: string): Promise<void> {
  await fetch(`${BASE}/projects/${id}`, { method: "DELETE" });
}

// --- Native file/folder browse dialogs ---

export async function browseFile(title: string, filter = "all"): Promise<string> {
  const r = await fetch(`${BASE}/browse/file?title=${encodeURIComponent(title)}&filter=${filter}`);
  if (!r.ok) throw new Error(await r.text());
  const { path } = await r.json();
  return path as string;
}

export async function browseDirectory(title: string): Promise<string> {
  const r = await fetch(`${BASE}/browse/directory?title=${encodeURIComponent(title)}`);
  if (!r.ok) throw new Error(await r.text());
  const { path } = await r.json();
  return path as string;
}

// --- Path-based linking (no upload) ---

export async function linkCameraTrack(
  projectId: string,
  path: string,
  format: string
): Promise<Project> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/link-camera-track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, format }),
    })
  );
}

export async function linkTargets(
  projectId: string,
  path: string,
  layout = "auto",
  epsg = ""
): Promise<{ project: Project; warning: string | null }> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/link-targets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, layout, epsg }),
    })
  );
}

export async function getProjectCrsInfo(
  projectId: string
): Promise<{ name: string | null; epsg: string | null; epsg_vert: string | null }> {
  return json(await fetch(`${BASE}/projects/${projectId}/crs-info`));
}

export async function linkImages(
  projectId: string,
  path: string
): Promise<{ count: number; project: Project }> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/link-images`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    })
  );
}

export async function linkDsm(
  projectId: string,
  path: string
): Promise<Project> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/link-dsm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    })
  );
}

// --- File uploads ---

export async function uploadCameraTrack(
  projectId: string,
  format: string,
  file: File,
  internalFile?: File
): Promise<Project> {
  const form = new FormData();
  form.append("format", format);
  form.append("file", file);
  if (internalFile) form.append("internal_file", internalFile);
  return json(
    await fetch(`${BASE}/projects/${projectId}/upload-camera-track`, {
      method: "POST",
      body: form,
    })
  );
}

export async function uploadTargets(
  projectId: string,
  file: File
): Promise<Project> {
  const form = new FormData();
  form.append("file", file);
  return json(
    await fetch(`${BASE}/projects/${projectId}/upload-targets`, {
      method: "POST",
      body: form,
    })
  );
}

export async function uploadImages(
  projectId: string,
  files: FileList
): Promise<{ uploaded: number }> {
  const form = new FormData();
  for (let i = 0; i < files.length; i++) {
    form.append("files", files[i]);
  }
  return json(
    await fetch(`${BASE}/projects/${projectId}/upload-images`, {
      method: "POST",
      body: form,
    })
  );
}

// --- Images ---

export async function listImages(projectId: string): Promise<string[]> {
  return json(await fetch(`${BASE}/projects/${projectId}/images/`));
}

export function imageUrl(projectId: string, imageName: string): string {
  return `${BASE}/projects/${projectId}/images/${imageName}/file`;
}

export async function getCoveringImages(
  projectId: string,
  targetId: string
): Promise<string[]> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/images/covering/${targetId}`)
  );
}

export async function getImageExif(
  projectId: string,
  imageName: string
): Promise<{ capture_time_utc: string; latitude: number; longitude: number; altitude_msl: number }> {
  return json(
    await fetch(`${BASE}/projects/${projectId}/images/${encodeURIComponent(imageName)}/exif`)
  );
}

// --- Marking ---

export async function getMarks(
  projectId: string,
  targetId: string
): Promise<MarkSet> {
  return json(
    await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/marks/`
    )
  );
}

export async function addMark(
  projectId: string,
  targetId: string,
  mark: ImageMark
): Promise<MarkSet> {
  return json(
    await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/marks/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mark),
      }
    )
  );
}

export async function replaceMarks(
  projectId: string,
  targetId: string,
  markSet: MarkSet
): Promise<MarkSet> {
  return json(
    await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/marks/`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(markSet),
      }
    )
  );
}

export interface MarkResidual {
  image_name: string;
  mark_type: "base" | "tip";
  pixel_x: number;
  pixel_y: number;
  reprojection_px: number | null;
  projected_x: number | null;
  projected_y: number | null;
  ground_deviation_m: number | null;
  pixels_per_meter: number | null;
}

export async function getResiduals(
  projectId: string,
  targetId: string
): Promise<MarkResidual[]> {
  try {
    const r = await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/marks/residuals`
    );
    if (!r.ok) return [];
    const data = await r.json();
    return data.marks as MarkResidual[];
  } catch {
    return [];
  }
}

export async function clearMarks(
  projectId: string,
  targetId: string
): Promise<MarkSet> {
  return json(
    await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/marks/`,
      { method: "DELETE" }
    )
  );
}

// --- Compute ---

export async function computeHeight(
  projectId: string,
  targetId: string,
): Promise<Measurement> {
  // Timestamp and GPS are read from image EXIF by the backend automatically.
  return json(
    await fetch(
      `${BASE}/projects/${projectId}/targets/${targetId}/compute`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }
    )
  );
}

// --- Export ---

export function exportUrl(projectId: string, format: string): string {
  return `${BASE}/projects/${projectId}/export?format=${format}`;
}
