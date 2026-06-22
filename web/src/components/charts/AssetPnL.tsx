import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compactMoney, money } from "../../lib/format";
import type { Trade } from "../../types";

export default function AssetPnL({ closed }: { closed: Trade[] }) {
  const map = new Map<string, number>();
  for (const t of closed) {
    if (t.pnl != null) map.set(t.asset, (map.get(t.asset) ?? 0) + t.pnl);
  }
  const data = [...map.entries()].map(([asset, pnl]) => ({
    asset,
    pnl: Math.round(pnl * 100) / 100,
  }));

  return (
    <div className="card panel">
      <div className="panel-head"><h2>Realized P&amp;L by asset</h2></div>
      {data.length ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 10, right: 8, left: 4, bottom: 0 }}>
            <XAxis dataKey="asset" stroke="#6a6a73" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis
              stroke="#6a6a73"
              fontSize={11}
              width={56}
              tickFormatter={(v) => compactMoney(Number(v))}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.05)" }}
              content={({ active, payload }: any) =>
                active && payload?.length ? (
                  <div className="chart-tip">
                    <div className="t-label">{payload[0].payload.asset}</div>
                    <div
                      className="t-val mono"
                      style={{ color: payload[0].payload.pnl >= 0 ? "#6fbf8e" : "#e27e6f" }}
                    >
                      {money(payload[0].payload.pnl)}
                    </div>
                  </div>
                ) : null
              }
            />
            <Bar dataKey="pnl" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.pnl >= 0 ? "#6fbf8e" : "#e27e6f"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="chart-empty">No closed trades yet — P&amp;L appears once positions close.</div>
      )}
    </div>
  );
}
