export default function ConfidenceBar({
  value,
  direction = "bullish",
}: {
  value: number;
  direction?: "bullish" | "bearish";
}) {
  const color = direction === "bullish" ? "var(--pos)" : "var(--neg)";
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="confbar">
      <div className="track">
        <div className="fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="val" style={{ color }}>{pct.toFixed(0)}%</span>
    </div>
  );
}
