import { dateTime } from "../lib/format";
import type { Evaluation, Prediction } from "../types";
import AccuracyBars from "./charts/AccuracyBars";
import AssetBadge from "./ui/AssetBadge";
import Card from "./ui/Card";
import ConfidenceBar from "./ui/ConfidenceBar";
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
        <div className="panel-head"><h2>Signal accuracy — is the strategy any good?</h2></div>
        <p className="sub">
          Every order-flow signal is scored against the real price after 24h and 7d. Pushes (no move) are excluded.
        </p>
        <AccuracyBars predictions={predictions} />
      </Card>

      <Card className="panel">
        <div className="panel-head"><h2>Recent signals</h2></div>
        <div className="scroll-x">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th><th>Asset</th><th>Call</th><th>Confidence</th>
                <th className="num">24h</th><th className="num">7d</th><th>Model</th>
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
                    <td style={{ minWidth: 150 }}><ConfidenceBar value={conf} direction={p.direction} /></td>
                    <td className="num"><Outcome ev={evalFor(p, "24h")} /></td>
                    <td className="num"><Outcome ev={evalFor(p, "7d")} /></td>
                    <td className="muted">{p.model}</td>
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
