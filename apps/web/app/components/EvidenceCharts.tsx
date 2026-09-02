"use client";

/**
 * Two SVG primitives for the scan result, written by hand rather than pulled
 * from a chart library: both are small, and both need to fail honestly.
 *
 * A chart in this product is a claim about evidence, so neither of these will
 * invent one. `CoverageDonut` renders an explicit "nothing was searched" ring
 * when the catalog is empty instead of a full circle of one colour, and
 * `ScoreRing` renders a dashed placeholder when a lane produced no number
 * rather than drawing a zero that would read as a measured result.
 */

const TAU = Math.PI * 2;

export type DonutSegment = {
  key: string;
  label: string;
  value: number;
  /** A CSS colour, normally a lane or decision token. */
  color: string;
  hint?: string;
};

export function CoverageDonut({
  segments,
  centre,
  centreLabel,
  size = 156,
}: {
  segments: DonutSegment[];
  centre: string;
  centreLabel: string;
  size?: number;
}) {
  const stroke = 13;
  const radius = (size - stroke) / 2;
  const circumference = TAU * radius;
  const drawn = segments.filter((segment) => segment.value > 0);
  const total = drawn.reduce((sum, segment) => sum + segment.value, 0);

  let offset = 0;

  return (
    <svg
      className="cpDonut"
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      role="img"
      aria-label={
        total > 0
          ? `${centre} ${centreLabel}. ${drawn.map((s) => `${s.value} ${s.label}`).join(", ")}.`
          : `${centre} ${centreLabel}.`
      }
    >
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={stroke}
          strokeDasharray={total > 0 ? undefined : "3 7"}
        />
        {drawn.map((segment) => {
          const length = (segment.value / total) * circumference;
          // A hairline gap keeps adjacent segments legible without implying a
          // quantity, so it is subtracted from the arc rather than added.
          const gap = drawn.length > 1 ? Math.min(3, length * 0.12) : 0;
          const dash = Math.max(length - gap, 0.6);
          const node = (
            <circle
              key={segment.key}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={segment.color}
              strokeWidth={stroke}
              strokeLinecap="butt"
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
            />
          );
          offset += length;
          return node;
        })}
      </g>
      <text className="cpDonutValue" x="50%" y="48%" textAnchor="middle" dominantBaseline="middle">
        {centre}
      </text>
      <text className="cpDonutLabel" x="50%" y="65%" textAnchor="middle" dominantBaseline="middle">
        {centreLabel}
      </text>
    </svg>
  );
}

/**
 * A 0..1 gauge. `value` of `null` is not zero: it means the lane returned no
 * number, and the ring says so rather than drawing an empty result.
 */
export function ScoreRing({
  value,
  display,
  caption,
  tone = "neutral",
  size = 62,
}: {
  value: number | null;
  display: string;
  caption: string;
  tone?: "positive" | "review" | "quiet" | "neutral";
  size?: number;
}) {
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circumference = TAU * radius;
  const clamped = value === null ? 0 : Math.max(0, Math.min(1, value));
  const dash = circumference * clamped;

  return (
    <svg
      className={`cpRing tone-${tone}${value === null ? " isEmpty" : ""}`}
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      role="img"
      aria-label={`${caption}: ${display}`}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        className="cpRingTrack"
        strokeDasharray={value === null ? "2 5" : undefined}
      />
      {value !== null && (
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          className="cpRingValue"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      )}
      <text className="cpRingText" x="50%" y="50%" textAnchor="middle" dominantBaseline="central">
        {display}
      </text>
    </svg>
  );
}

/**
 * The origin lane's two scores plotted against each other.
 *
 * The lane is routinely misread, because a signal of 0 next to "the origin
 * could not be established" looks like proof that no AI was involved. It is
 * not: the second score says how far the first can be trusted at all, and the
 * engine will not call anything a finding until both hold up. Two bars side by
 * side state that relationship but do not show it, so the position of one mark
 * in a field carries it instead.
 *
 * The vertical fog is the honest part. Evidence quality gates the reading, but
 * the cut-off is the engine's to declare and is not published as a number, so
 * the fog thickens continuously toward the floor rather than drawing a
 * threshold line this component would have to invent. Geometry places the
 * scan; only the engine's own words name the result.
 */
export function OriginField({
  signal,
  quality,
  size = 288,
}: {
  /** 0..100, or null when the lane returned no measurement. */
  signal: number | null;
  quality: number | null;
  size?: number;
}) {
  const left = 44;
  const top = 12;
  const w = size - left - 14;
  const h = size - top - 42;
  // The plotting area is inset from the frame so a reading of 0 or 100 still
  // draws a whole mark inside the field, clear of the zone labels, rather than
  // half a dot bleeding over the border.
  const padX = 26;
  const padY = 44;
  const plotted = signal !== null && quality !== null;
  const clamp = (n: number) => Math.max(0, Math.min(100, n));
  const x = left + padX + (clamp(signal ?? 0) / 100) * (w - padX * 2);
  const y = top + h - padY - (clamp(quality ?? 0) / 100) * (h - padY * 2);

  return (
    <svg
      className={`cpOriginField${plotted ? "" : " isEmpty"}`}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={
        plotted
          ? `AI signal ${signal} of 100, evidence quality ${quality} of 100. A finding requires both.`
          : "This lane returned no measurement to plot."
      }
    >
      <defs>
        {/* Horizontal: signal strength. Vertical: the fog that cancels it. The
            two are kept on separate axes so the picture says "a strong signal
            low down still means nothing" rather than blending into one blob. */}
        <linearGradient id="cpOriginLift" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--cp-lane-origin)" stopOpacity="0.02" />
          <stop offset="100%" stopColor="var(--cp-lane-origin)" stopOpacity="0.52" />
        </linearGradient>
        <linearGradient id="cpOriginFog" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#04060a" stopOpacity="0.96" />
          <stop offset="34%" stopColor="#04060a" stopOpacity="0.72" />
          <stop offset="70%" stopColor="#04060a" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#04060a" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="cpOriginHalo">
          <stop offset="0%" stopColor="var(--cp-lane-origin)" stopOpacity="0.60" />
          <stop offset="100%" stopColor="var(--cp-lane-origin)" stopOpacity="0" />
        </radialGradient>
        <clipPath id="cpOriginClip">
          <rect x={left} y={top} width={w} height={h} rx="10" />
        </clipPath>
      </defs>

      <rect x={left} y={top} width={w} height={h} rx="10" fill="url(#cpOriginLift)" />
      <g className="cpOriginGrid" aria-hidden="true">
        {[0.25, 0.5, 0.75].map((t) => (
          <line key={`v${t}`} x1={left + w * t} y1={top} x2={left + w * t} y2={top + h} />
        ))}
        {[0.25, 0.5, 0.75].map((t) => (
          <line key={`h${t}`} x1={left} y1={top + h * t} x2={left + w} y2={top + h * t} />
        ))}
      </g>
      <rect x={left} y={top} width={w} height={h} rx="10" fill="url(#cpOriginFog)" />
      <rect x={left} y={top} width={w} height={h} rx="10" className="cpOriginFrame" />

      <text className="cpOriginZone" x={left + w - 12} y={top + 19} textAnchor="end">
        AI INDICATORS
      </text>
      <text className="cpOriginZone" x={left + 12} y={top + 19}>
        NO AI INDICATORS
      </text>
      <text className="cpOriginZone isMuted" x={left + w / 2} y={top + h - 11} textAnchor="middle">
        TOO LITTLE EVIDENCE TO CONCLUDE
      </text>

      {plotted && (
        <g className="cpOriginMark" clipPath="url(#cpOriginClip)">
          <circle cx={x} cy={y} r="26" fill="url(#cpOriginHalo)" />
          {/* Drawn back to the plot bounds rather than the frame, so the guides
              never run through the zone labels sitting in the frame margins. */}
          <line x1={left + padX} y1={y} x2={x} y2={y} />
          <line x1={x} y1={top + h - padY} x2={x} y2={y} />
          <circle cx={x} cy={y} r="7" className="cpOriginDot" />
        </g>
      )}
      {!plotted && (
        <text className="cpOriginEmpty" x={left + w / 2} y={top + h / 2} textAnchor="middle">
          NOTHING TO PLOT
        </text>
      )}

      <text className="cpOriginAxis" x={left + w / 2} y={size - 10} textAnchor="middle">
        AI SIGNAL →
      </text>
      <text
        className="cpOriginAxis"
        x={14}
        y={top + h / 2}
        textAnchor="middle"
        transform={`rotate(-90 14 ${top + h / 2})`}
      >
        EVIDENCE QUALITY →
      </text>
      <text className="cpOriginTick" x={left + padX} y={top + h + 16} textAnchor="middle">
        0
      </text>
      <text className="cpOriginTick" x={left + w - padX} y={top + h + 16} textAnchor="middle">
        100
      </text>
    </svg>
  );
}

/**
 * A horizontal 0..1 bar for paired measurements that read better side by side
 * than as two rings — the origin lane's signal strength against the quality of
 * the evidence behind it, where the second number qualifies the first.
 */
export function MetricBar({
  label,
  value,
  display,
  tone = "neutral",
}: {
  label: string;
  value: number | null;
  display: string;
  tone?: "positive" | "review" | "quiet" | "neutral";
}) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={`cpMetricBar tone-${tone}`}>
      <div className="cpMetricBarHead">
        <span>{label}</span>
        <b>{display}</b>
      </div>
      <div className="cpMetricBarTrack" aria-hidden="true">
        {value !== null && <i style={{ width: `${width}%` }} />}
      </div>
    </div>
  );
}
