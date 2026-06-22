import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";

export default function Sparkline({
  data,
  color = "#8fa97c",
}: {
  data: number[];
  color?: string;
}) {
  const gid = "spark-" + useId().replace(/:/g, "");
  if (data.length < 2) return null;
  const chartData = data.map((v, i) => ({ i, v }));

  return (
    <ResponsiveContainer width="100%" height={36}>
      <AreaChart data={chartData} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#${gid})`}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
