import { compactMoney, dateTime, money, num, pct, signClass } from "../lib/format";
import type { EquitySnapshot, Trade } from "../types";
import AllocationDonut from "./charts/AllocationDonut";
import AssetPnL from "./charts/AssetPnL";
import EquityChart from "./charts/EquityChart";
import AssetBadge from "./ui/AssetBadge";
import GlassCard from "./ui/GlassCard";
import Pill from "./ui/Pill";
import StatCard from "./ui/StatCard";

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
  const equitySpark = equity.map((e) => e.equity);

  return (
    <div className="stack">
      <div className="grid">
        <StatCard
          label="Equity"
          value={latest ? latest.equity : null}
          format={compactMoney}
          sub={totalReturn !== null ? `${pct(totalReturn)} since start` : "live"}
          valueClass={totalReturn !== null ? signClass(totalReturn) : undefined}
          spark={equitySpark}
          sparkColor="#7c5cff"
          delay={0}
        />
        <StatCard
          label="Cash"
          value={latest ? latest.cash : null}
          format={compactMoney}
          sub="available USDT"
          delay={0.06}
        />
        <StatCard
          label="Realized P&L"
          value={realized}
          format={money}
          valueClass={signClass(realized)}
          sub={winRate !== null ? `${wins}/${decided.length} wins · ${winRate.toFixed(0)}%` : "no closed trades yet"}
          delay={0.12}
        />
        <StatCard
          label="Open positions"
          value={open.length}
          format={(n) => String(Math.round(n))}
          sub={`${closed.length} closed`}
          delay={0.18}
        />
      </div>

      <EquityChart equity={equity} />

      <div className="grid-2">
        <AllocationDonut open={open} />
        <AssetPnL closed={closed} />
      </div>

      <GlassCard className="panel" delay={0.1}>
        <div className="panel-head"><h2>Open positions</h2></div>
        {open.length ? (
          <div className="scroll-x">
            <table className="table">
              <thead>
                <tr>
                  <th>Asset</th><th>Side</th>
                  <th className="num">Qty</th><th className="num">Entry</th><th className="num">Notional</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {open.map((t) => (
                  <tr key={t.id}>
                    <td><AssetBadge symbol={t.asset} /></td>
                    <td><Pill kind={t.side}>{t.side}</Pill></td>
                    <td className="num mono">{num(t.qty, 4)}</td>
                    <td className="num mono">{money(t.entry_price)}</td>
                    <td className="num mono">{money(t.notional)}</td>
                    <td className="muted">{dateTime(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-note">No open positions right now — the bot is waiting for a high-confidence signal.</p>
        )}
      </GlassCard>
    </div>
  );
}
