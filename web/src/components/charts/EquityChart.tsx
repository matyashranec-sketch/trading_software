import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compactMoney, dateTime, money } from "../../lib/format";
import type { EquitySnapshot } from "../../types";

type Range = "24h" | "7d" | "all";
const RANGES: { id: Range; label: string; ms: number }[] = [
  { id: "24h", label: "24h", ms: 24 * 3600e3 },
  { id: "7d", label: "7d", ms: 7 * 24 * 3600e3 },
  { id: "all", label: "All", ms: Number.POSITIVE_INFINITY },
];

function toMs(ts: string): number {
  const iso = ts.endsWith("Z") ? ts : `${ts}Z`;
  return new Date(iso).getTime();
}

function Tip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tip">
      <div className="t-label">{dateTime(p.ts)}</div>
      <div className="t-val gradient-text">{money(p.equity)}</div>
    </div>
  );
}

export default function EquityChart({ equity }: { equity: EquitySnapshot[] }) {
  const [range, setRange] = useState<Range>("all");

  const chartData = useMemo(() => {
    const sorted = [...equity].sort((a, b) => toMs(a.ts) - toMs(b.ts));
    const r = RANGES.find((x) => x.id === range);
    let rows = sorted;
    if (r && r.ms !== Number.POSITIVE_INFINITY) {
      const cutoff = Date.now() - r.ms;
      const filtered = sorted.filter((e) => toMs(e.ts) >= cutoff);
      if (filtered.length > 1) rows = filtered;
    }
    return rows.map((e) => ({ ts: e.ts, equity: Math.round(e.equity * 100) / 100 }));
  }, [equity, range]);

  return (
    <div className="glass panel">
      <div className="panel-head">
        <h2>Equity curve</h2>
        <div className="filters">
          {RANGES.map((r) => (
            <button
              key={r.id}
              className={`chip ${range === r.id ? "active" : ""}`}
              onClick={() => setRange(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={chartData} margin={{ top: 10, right: 8, left: 4, bottom: 0 }}>
            <defs>
              <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#7c5cff" stopOpacity={0.45} />
                <stop offset="55%" stopColor="#00e0b8" stopOpacity={0.12} />
                <stop offset="100%" stopColor="#00e0b8" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="eq-stroke" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#7c5cff" />
                <stop offset="100%" stopColor="#00e0b8" />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(124,92,255,0.1)" vertical={false} />
            <XAxis
              dataKey="ts"
              tickFormatter={(v) => dateTime(String(v))}
              stroke="#5e5d78"
              fontSize={11}
              minTickGap={56}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#5e5d78"
              fontSize={11}
              width={56}
              domain={["auto", "auto"]}
              tickFormatter={(v) => compactMoney(Number(v))}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<Tip />} cursor={{ stroke: "rgba(124,92,255,0.4)", strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="url(#eq-stroke)"
              strokeWidth={2.5}
              fill="url(#eq-fill)"
              dot={false}
              activeDot={{ r: 4, fill: "#00e0b8", stroke: "#07070d", strokeWidth: 2 }}
              isAnimationActive
              animationDuration={900}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div className="chart-empty">
          <div className="big">📈</div>
          <div>Not enough data yet — the curve fills in after a few bot cycles.</div>
        </div>
      )}
    </div>
  );
}
