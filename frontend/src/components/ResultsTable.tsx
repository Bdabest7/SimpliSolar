import type { Measurement } from "../types";

interface Props {
  measurements: Measurement[];
}

function confColor(value: number): string {
  if (value < 0.01) return "var(--success)";
  if (value < 0.05) return "var(--warning)";
  return "var(--danger)";
}

function mm(metres: number): string {
  return (metres * 1000).toFixed(1);
}

export default function ResultsTable({ measurements }: Props) {
  if (measurements.length === 0) return null;

  return (
    <div className="results-bar">
      <table>
        <thead>
          <tr>
            <th>Target</th>
            <th title="Absolute Z elevation of object top — the critical measurement">
              Object Top Z
            </th>
            <th>Height (m)</th>
            <th>Ground Z</th>
            <th>Shadow (m)</th>
            <th>Sun Alt</th>
            <th title="Object-top triangulation RMS residual">Top Res.</th>
            <th title="Per-image Object Top Z scatter — primary confidence metric">
              Z Spread
            </th>
            <th title="Scatter of per-image tip ground positions">Tip Spread</th>
            <th title="DTM pixel resolution">DTM Cell</th>
            <th title="Number of tip images used">N</th>
          </tr>
        </thead>
        <tbody>
          {measurements.map((m) => {
            const topZ =
              m.object_top_z !== 0
                ? m.object_top_z
                : m.base_z + m.computed_height;
            return (
              <tr key={m.target_id}>
                <td>{m.target_id}</td>
                <td style={{ fontWeight: 700 }}>{topZ.toFixed(3)}</td>
                <td>{m.computed_height.toFixed(4)}</td>
                <td>{m.base_z.toFixed(3)}</td>
                <td>{m.shadow_length_horizontal.toFixed(3)}</td>
                <td>{m.sun_altitude_deg.toFixed(2)}&deg;</td>
                <td style={{ color: confColor(m.top_residual) }}>
                  {mm(m.top_residual)}mm
                </td>
                <td
                  style={{
                    color: confColor(m.object_top_z_spread),
                    fontWeight: 600,
                  }}
                >
                  {m.object_top_z_spread > 0
                    ? `${mm(m.object_top_z_spread)}mm`
                    : "—"}
                </td>
                <td style={{ color: confColor(m.tip_spread) }}>
                  {m.tip_spread > 0 ? `${mm(m.tip_spread)}mm` : "—"}
                </td>
                <td style={{ color: "var(--text-muted)", fontSize: 11 }}>
                  {m.dtm_cell_size > 0
                    ? `${mm(m.dtm_cell_size)}mm`
                    : "—"}
                </td>
                <td style={{ color: "var(--text-muted)" }}>
                  {m.n_tip_images || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
