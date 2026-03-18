import { exportUrl } from "../api/client";

interface Props {
  projectId: string;
  hasMeasurements: boolean;
}

export default function ExportPanel({ projectId, hasMeasurements }: Props) {
  if (!hasMeasurements) return null;

  return (
    <div className="export-panel">
      <h3>Export Checkpoints</h3>
      <div style={{ display: "flex", gap: 8 }}>
        <a href={exportUrl(projectId, "pix4d")} download>
          <button className="primary">Pix4D CSV</button>
        </a>
        <a href={exportUrl(projectId, "metashape")} download>
          <button className="primary">Metashape CSV</button>
        </a>
      </div>
    </div>
  );
}
