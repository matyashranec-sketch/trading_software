import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { dateTime, money, num, pct, signClass } from "../lib/format";
import type { EquitySnapshot, Trade } from "../types";

function Stat({ label, value, sub, valueClass }: {
  label: string; value: string; sub?: string; valueClass?: string;
}) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={`value ${valueClass ?? ""}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export default function Dashboard({ equity, trades }: { equity: EquitySnapshot[]; trades: Trade[] }) {
  const latest = equity.length ? equity[equity.length - 1] : undefined;
  const first = equity.length ? equity[0] : undefined;
  const open = trades.filter((t) => t.status === "open" || t.status === "submitted");
  const closed = trades.filter((t) => t.status === "closed");
  const realized = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const decided = closed.filter((t) => t.pnl !== null);
  const wins = decided.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = decided.length ? (wins / decided.length) * 100 : null;
  const totalReturn = latest && first && first.equity ? (latest.equity / first.equity - 1) * 100 : null;

  const chartData = equity.map((e) => ({ ts: e.ts, equity: Math.round(e.equity * 100) / 100 }));

  return (
    <>
      <div className="grid">
        <Stat
          label="Equity"
          value={money(latest?.equity)}
          sub={totalReturn !== null ? `${pct(totalReturn)} since start` : undefined}
          valueClass={totalReturn !== null ? signClass(totalReturn) : undefined}
        />
        <Stat label="Cash" value={money(latest?.cash)} />
        <Stat
          label="Realized P&L"
          value={money(realized)}
          valueClass={signClass(realized)}
          sub={winRate !== null ? `${wins}/${decided.length} wins · ${winRate.toFixed(0)}% win rate` : undefined}
        />
        <Stat label="Open positions" value={String(open.length)} />
      </div>

      <div className="panel">
        <h2>Equity curve</h2>
        {chartData.length > 1 ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid stroke="#233047" strokeDasharray="3 3" />
              <XAxis
                dataKey="ts"
                tickFormatter={(v) => dateTime(v)}
                stroke="#8593a8"
                fontSize={11}
                minTickGap={48}
              />
              <YAxis
                stroke="#8593a8"
                fontSize={11}
                width={70}
                domain={["auto", "auto"]}
                tickFormatter={(v) => money(v, 0)}
              />
              <Tooltip
                contentStyle={{ background: "#0a0e16", border: "1px solid #233047", borderRadius: 8 }}
                labelFormatter={(v) => dateTime(String(v))}
                formatter={(v: number) => [money(v), "Equity"]}
              />
              <Line type="monotone" dataKey="equity" stroke="#5b8cff" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="muted">Not enough data yet — the equity curve appears after a few bot runs.</p>
        )}
      </div>

      <div className="panel">
        <h2>Open positions</h2>
        {open.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Notional</th>
                <th>Model</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {open.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.asset}</strong></td>
                  <td><span className={`pill ${t.side}`}>{t.side}</span></td>
                  <td className="num">{num(t.qty, 4)}</td>
                  <td className="num">{money(t.entry_price)}</td>
                  <td className="num">{money(t.notional)}</td>
                  <td className="muted">{t.model}</td>
                  <td className="muted">{dateTime(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No open positions right now.</p>
        )}
      </div>
    </>
  );
}
