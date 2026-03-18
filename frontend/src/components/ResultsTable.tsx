import type { Measurement } from "../types";

interface Props {
  measurements: Measurement[];
}

export default function ResultsTable({ measurements }: Props) {
  if (measurements.length === 0) return null;

  return (
    <div className="results-bar">
      <table>
        <thead>
          <tr>
            <th>Target</th>
            <th>Height (m)</th>
            <th>Ground Z</th>
            <th>Object Top Z</th>
            <th>Shadow (m)</th>
            <th>Sun Alt</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {measurements.map((m) => (
            <tr key={m.target_id}>
              <td>{m.target_id}</td>
              <td style={{ fontWeight: 600 }}>{m.computed_height.toFixed(4)}</td>
              <td>{m.base_z.toFixed(3)}</td>
              <td>{(m.base_z + m.computed_height).toFixed(3)}</td>
              <td>{m.shadow_length_horizontal.toFixed(3)}</td>
              <td>{m.sun_altitude_deg.toFixed(2)}&deg;</td>
              <td
                style={{
                  color:
                    m.confidence < 0.01
                      ? "var(--success)"
                      : m.confidence < 0.05
                      ? "var(--warning)"
                      : "var(--danger)",
                }}
              >
                {(m.confidence * 1000).toFixed(1)}mm
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
