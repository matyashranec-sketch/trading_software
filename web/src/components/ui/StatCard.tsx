import CountUp from "./CountUp";
import GlassCard from "./GlassCard";
import Sparkline from "./Sparkline";

export default function StatCard({
  label,
  value,
  format,
  sub,
  valueClass,
  spark,
  sparkColor,
  delay = 0,
}: {
  label: string;
  value: number | null;
  format: (n: number) => string;
  sub?: string;
  valueClass?: string;
  spark?: number[];
  sparkColor?: string;
  delay?: number;
}) {
  return (
    <GlassCard className="stat" delay={delay}>
      <div className="label">{label}</div>
      <div className={`value mono ${valueClass ?? ""}`}>
        {value === null ? "—" : <CountUp value={value} format={format} />}
      </div>
      {sub && <div className="sub">{sub}</div>}
      {spark && spark.length > 1 && (
        <div className="spark">
          <Sparkline data={spark} color={sparkColor} />
        </div>
      )}
    </GlassCard>
  );
}
