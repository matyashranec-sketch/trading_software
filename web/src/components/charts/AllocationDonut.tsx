import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { money } from "../../lib/format";
import type { Trade } from "../../types";

const PALETTE = ["#7c5cff", "#00e0b8", "#f7931a", "#8a92ff", "#ff5c7a", "#ffcf5c", "#14f195"];

export default function AllocationDonut({ open }: { open: Trade[] }) {
  const map = new Map<string, number>();
  for (const t of open) {
    const v = t.notional ?? 0;
    if (v > 0) map.set(t.asset, (map.get(t.asset) ?? 0) + v);
  }
  const data = [...map.entries()].map(([name, value]) => ({ name, value }));
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <div className="glass panel">
      <div className="panel-head"><h2>Portfolio allocation</h2></div>
      {data.length ? (
        <>
          <div style={{ position: "relative", height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={64}
                  outerRadius={94}
                  paddingAngle={3}
                  stroke="none"
                  startAngle={90}
                  endAngle={-270}
                >
                  {data.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }: any) =>
                    active && payload?.length ? (
                      <div className="chart-tip">
                        <div className="t-label">{payload[0].name}</div>
                        <div className="t-val">{money(payload[0].value)}</div>
                      </div>
                    ) : null
                  }
                />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none" }}>
              <div className="donut-center">
                <div className="v mono">{data.length}</div>
                <div className="l">{data.length === 1 ? "position" : "positions"}</div>
              </div>
            </div>
          </div>
          <div className="legend">
            {data.map((d, i) => (
              <span className="item" key={d.name}>
                <span className="swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
                {d.name} · {total ? ((d.value / total) * 100).toFixed(0) : 0}%
              </span>
            ))}
          </div>
        </>
      ) : (
        <div className="chart-empty">
          <div className="big">🧊</div>
          <div>No open positions yet.</div>
        </div>
      )}
    </div>
  );
}
