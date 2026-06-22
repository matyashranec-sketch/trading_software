import { motion } from "framer-motion";

export default function ConfidenceBar({
  value,
  direction = "bullish",
}: {
  value: number;
  direction?: "bullish" | "bearish";
}) {
  const color = direction === "bullish" ? "#2ee6a8" : "#ff5c7a";
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="confbar">
      <div className="track">
        <motion.div
          className="fill"
          style={{ background: color, boxShadow: `0 0 12px -2px ${color}` }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        />
      </div>
      <span className="val" style={{ color }}>{pct.toFixed(0)}%</span>
    </div>
  );
}
