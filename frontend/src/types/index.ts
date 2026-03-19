/** TypeScript interfaces mirroring the backend Pydantic models. */

export interface CameraIntrinsics {
  focal_length_px: number;
  cx: number;
  cy: number;
  k1: number;
  k2: number;
  k3: number;
  p1: number;
  p2: number;
  image_width: number;
  image_height: number;
}

export interface CameraExtrinsics {
  x: number;
  y: number;
  z: number;
  omega: number;
  phi: number;
  kappa: number;
}

export interface Target {
  id: string;
  label: string;
  x: number;
  y: number;
  z: number | null;
}

export interface Measurement {
  target_id: string;
  base_x: number;
  base_y: number;
  base_z: number;
  tip_x: number;
  tip_y: number;
  tip_z: number;
  shadow_length_horizontal: number;
  sun_altitude_deg: number;
  sun_azimuth_deg: number;
  computed_height: number;
  confidence: number;
  top_residual: number;
  tip_residual: number;
  shadow_length_confidence: number;
  height_confidence: number;
  // Per-image ray-to-ground fields
  object_top_z: number;
  object_top_z_spread: number;
  tip_spread: number;
  per_image_object_top_z: number[];
  n_tip_images: number;
  method: string;
  dsm_cell_size: number;
  timestamp_utc: string;
}

export type ProjectStatus = "created" | "ingested" | "marking" | "computed";

export interface Project {
  id: string;
  name: string;
  created_at: string;
  status: ProjectStatus;
  camera_track_format: string;
  // Path-based fields
  camera_track_path: string;
  image_dir: string;
  target_csv: string;
  dsm_path: string;
  // Legacy upload-based fields
  camera_track_file: string;
  target_file: string;
  targets: Target[];
  measurements: Measurement[];
}

export type MarkType = "base" | "tip";

export interface ImageMark {
  image_name: string;
  mark_type: MarkType;
  pixel_x: number;
  pixel_y: number;
}

export interface MarkSet {
  target_id: string;
  marks: ImageMark[];
}
