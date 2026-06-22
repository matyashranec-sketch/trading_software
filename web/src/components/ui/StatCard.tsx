import Card from "./Card";
import Sparkline from "./Sparkline";

export default function StatCard({
  label,
  value,
  format,
  sub,
  valueClass,
  spark,
  sparkColor,
}: {
  label: string;
  value: number | null;
  format: (n: number) => string;
  sub?: string;
  valueClass?: string;
  spark?: number[];
  sparkColor?: string;
}) {
  return (
    <Card className="stat">
      <div className="label">{label}</div>
      <div className={`value mono ${valueClass ?? ""}`}>
        {value === null ? "—" : format(value)}
      </div>
      {sub && <div className="sub">{sub}</div>}
      {spark && spark.length > 1 && (
        <div className="spark">
          <Sparkline data={spark} color={sparkColor} />
        </div>
      )}
    </Card>
  );
}
