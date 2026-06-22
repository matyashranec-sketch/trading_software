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
    <div className="glass panel">
      <div className="panel-head"><h2>Realized P&amp;L by asset</h2></div>
      {data.length ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 10, right: 8, left: 4, bottom: 0 }}>
            <XAxis dataKey="asset" stroke="#5e5d78" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis
              stroke="#5e5d78"
              fontSize={11}
              width={56}
              tickFormatter={(v) => compactMoney(Number(v))}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(124,92,255,0.08)" }}
              content={({ active, payload }: any) =>
                active && payload?.length ? (
                  <div className="chart-tip">
                    <div className="t-label">{payload[0].payload.asset}</div>
                    <div
                      className="t-val"
                      style={{ color: payload[0].payload.pnl >= 0 ? "#2ee6a8" : "#ff5c7a" }}
                    >
                      {money(payload[0].payload.pnl)}
                    </div>
                  </div>
                ) : null
              }
            />
            <Bar dataKey="pnl" radius={[6, 6, 0, 0]} isAnimationActive animationDuration={800}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.pnl >= 0 ? "#2ee6a8" : "#ff5c7a"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="chart-empty">
          <div className="big">💹</div>
          <div>No closed trades yet — P&amp;L appears once positions close.</div>
        </div>
      )}
    </div>
  );
}
