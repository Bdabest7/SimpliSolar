/**
 * Loading animation in the style of the Chrome T-Rex game:
 * two-tone (light gray on dark), flat pixel aesthetic.
 *
 * A sun arcs across the sky. A fence post casts a shadow that
 * stretches into the FOREGROUND (toward the viewer / bottom of screen)
 * — long at sunrise, short at noon, long again at sunset.
 */

interface Props {
  message?: string;
}

export default function ShadowLoader({ message }: Props) {
  return (
    <div style={{ textAlign: "center", padding: "32px 0" }}>
      <svg
        viewBox="0 0 320 180"
        width="320"
        height="180"
        style={{ display: "block", margin: "0 auto" }}
      >
        {/* sky */}
        <rect x="0" y="0" width="320" height="100" fill="#1a1d27" />

        {/* sun — arcs across the sky, 2-tone circle */}
        <g>
          <animateTransform
            attributeName="transform"
            type="translate"
            values="30,90; 80,30; 160,16; 240,30; 290,90"
            keyTimes="0; 0.25; 0.5; 0.75; 1"
            dur="4s"
            repeatCount="indefinite"
          />
          <circle r="12" fill="none" stroke="#535353" strokeWidth="2" />
          <circle r="10" fill="#535353" />
        </g>

        {/* ground line */}
        <line x1="0" y1="100" x2="320" y2="100" stroke="#535353" strokeWidth="2" />

        {/* ground fill */}
        <rect x="0" y="100" width="320" height="80" fill="#1a1d27" />

        {/* shadow — stretches INTO foreground (below ground line, toward bottom) */}
        <g>
          <polygon fill="#2a2d3a">
            <animate
              attributeName="points"
              values="
                155,102 165,102 220,170 210,170;
                155,102 165,102 190,150 180,150;
                155,102 165,102 162,115 158,115;
                155,102 165,102 130,150 120,150;
                155,102 165,102 100,170 90,170
              "
              keyTimes="0; 0.25; 0.5; 0.75; 1"
              dur="4s"
              repeatCount="indefinite"
            />
          </polygon>
        </g>

        {/* fence left rail */}
        <rect x="20" y="78" width="138" height="2" fill="#535353" />
        <rect x="20" y="88" width="138" height="2" fill="#535353" />

        {/* fence right rail */}
        <rect x="162" y="78" width="138" height="2" fill="#535353" />
        <rect x="162" y="88" width="138" height="2" fill="#535353" />

        {/* secondary post left */}
        <rect x="76" y="72" width="4" height="28" fill="#535353" />
        <rect x="74" y="70" width="8" height="3" fill="#535353" />

        {/* secondary post right */}
        <rect x="240" y="72" width="4" height="28" fill="#535353" />
        <rect x="238" y="70" width="8" height="3" fill="#535353" />

        {/* main fence post (centre) */}
        <rect x="156" y="66" width="8" height="34" fill="#535353" />
        <rect x="154" y="63" width="12" height="4" fill="#535353" />

        {/* ground texture — small dashes like T-Rex game */}
        <g stroke="#2a2d3a" strokeWidth="1">
          <line x1="12" y1="110" x2="22" y2="110" />
          <line x1="50" y1="125" x2="56" y2="125" />
          <line x1="95" y1="115" x2="103" y2="115" />
          <line x1="200" y1="130" x2="210" y2="130" />
          <line x1="260" y1="112" x2="268" y2="112" />
          <line x1="280" y1="140" x2="286" y2="140" />
          <line x1="35" y1="145" x2="42" y2="145" />
          <line x1="145" y1="155" x2="152" y2="155" />
        </g>
      </svg>

      {message && (
        <p
          style={{
            marginTop: 12,
            fontSize: 13,
            color: "#535353",
            fontFamily: "monospace",
            animation: "pulse 1.5s ease-in-out infinite",
          }}
        >
          {message}
        </p>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.5; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
