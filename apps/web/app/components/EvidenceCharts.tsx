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
