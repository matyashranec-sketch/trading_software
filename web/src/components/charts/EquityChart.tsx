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
import { dateTime, money } from "../../lib/format";
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
      <div className="t-val mono">{money(p.equity)}</div>
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
    <div className="card panel">
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
                <stop offset="0%" stopColor="#8fa97c" stopOpacity={0.18} />
                <stop offset="100%" stopColor="#8fa97c" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis
              dataKey="ts"
              tickFormatter={(v) => dateTime(String(v))}
              stroke="#6a6a73"
              fontSize={11}
              minTickGap={56}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#6a6a73"
              fontSize={11}
              width={66}
              domain={["auto", "auto"]}
              tickFormatter={(v) => money(Number(v), 0)}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<Tip />} cursor={{ stroke: "rgba(255,255,255,0.2)", strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#8fa97c"
              strokeWidth={1.75}
              fill="url(#eq-fill)"
              dot={false}
              activeDot={{ r: 3, fill: "#a5be90", stroke: "#131316", strokeWidth: 2 }}
              isAnimationActive={false}
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
