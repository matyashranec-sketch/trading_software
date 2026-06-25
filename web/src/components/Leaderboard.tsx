import { dateTime } from "../lib/format";
import type { Evaluation, Prediction } from "../types";
import AccuracyBars from "./charts/AccuracyBars";
import AssetBadge from "./ui/AssetBadge";
import Card from "./ui/Card";
import ConfluenceBar from "./ui/ConfluenceBar";
import Pill from "./ui/Pill";

function evalFor(p: Prediction, horizon: string): Evaluation | undefined {
  return (p.evaluations ?? []).find((e) => e.horizon === horizon);
}

function Outcome({ ev }: { ev?: Evaluation }) {
  if (!ev || ev.status !== "evaluated") return <span className="faint">·</span>;
  if (ev.is_correct === null) return <span className="muted">=</span>;
  return ev.is_correct ? <span className="pos">✓</span> : <span className="neg">✗</span>;
}

export default function Leaderboard({ predictions }: { predictions: Prediction[] }) {
  if (!predictions.length) {
    return (
      <Card className="panel">
        <p className="empty-note">No signals recorded yet — they appear after the bot's first cycles.</p>
      </Card>
    );
  }

  return (
    <div className="stack">
      <Card className="panel">
        <div className="panel-head"><h2>Directional hit-rate — a rough sanity check</h2></div>
        <p className="sub">
          Each order-flow signal's direction is scored against the real price after 24h and 7d
          (pushes excluded). It's only a rough proxy — the real performance is the P&L on the
          Dashboard and in Trades.
        </p>
        <AccuracyBars predictions={predictions} />
      </Card>

      <Card className="panel">
        <div className="panel-head"><h2>Recent signals</h2></div>
        <div className="scroll-x">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th><th>Asset</th><th>Call</th><th>Confluence</th>
                <th className="num">24h</th><th className="num">7d</th>
              </tr>
            </thead>
            <tbody>
              {predictions.slice(0, 50).map((p) => {
                const conf = Math.max(p.bullish_prob, p.bearish_prob);
                return (
                  <tr key={p.id}>
                    <td className="muted">{dateTime(p.created_at)}</td>
                    <td><AssetBadge symbol={p.asset} /></td>
                    <td><Pill kind={p.direction}>{p.direction === "bullish" ? "long" : "short"}</Pill></td>
                    <td style={{ minWidth: 150 }}><ConfluenceBar value={conf} direction={p.direction} /></td>
                    <td className="num"><Outcome ev={evalFor(p, "24h")} /></td>
                    <td className="num"><Outcome ev={evalFor(p, "7d")} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
