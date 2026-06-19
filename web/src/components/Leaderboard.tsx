import { dateTime, pct } from "../lib/format";
import type { Evaluation, Prediction } from "../types";

const HORIZONS = ["24h", "7d"];

type Tally = { correct: number; incorrect: number; pending: number };
const emptyTally = (): Tally => ({ correct: 0, incorrect: 0, pending: 0 });

function add(t: Tally, ev: Evaluation) {
  if (ev.status !== "evaluated") t.pending++;
  else if (ev.is_correct === null) return; // push — excluded from accuracy
  else if (ev.is_correct) t.correct++;
  else t.incorrect++;
}

function accuracy(t: Tally): number | null {
  const decided = t.correct + t.incorrect;
  return decided ? (t.correct / decided * 100) : null;
}

function evalFor(p: Prediction, horizon: string): Evaluation | undefined {
  return (p.evaluations ?? []).find((e) => e.horizon === horizon);
}

function Outcome({ ev }: { ev?: Evaluation }) {
  if (!ev || ev.status !== "evaluated") return <span className="muted">·</span>;
  if (ev.is_correct === null) return <span className="muted">=</span>;
  return ev.is_correct ? <span className="pos">✓</span> : <span className="neg">✗</span>;
}

export default function Leaderboard({ predictions }: { predictions: Prediction[] }) {
  const byModel = new Map<string, Record<string, Tally>>();
  for (const p of predictions) {
    const row = byModel.get(p.model) ?? Object.fromEntries(HORIZONS.map((h) => [h, emptyTally()]));
    for (const ev of p.evaluations ?? []) {
      if (row[ev.horizon]) add(row[ev.horizon], ev);
    }
    byModel.set(p.model, row);
  }
  const models = [...byModel.entries()].sort((a, b) => {
    const aa = accuracy(a[1]["24h"]) ?? -1;
    const bb = accuracy(b[1]["24h"]) ?? -1;
    return bb - aa;
  });

  if (!predictions.length) {
    return (
      <div className="panel">
        <p className="muted">No signals recorded yet.</p>
      </div>
    );
  }

  return (
    <>
      <div className="panel">
        <h2>Model accuracy — is the AI any good?</h2>
        <p className="muted" style={{ marginTop: -4 }}>
          Every signal is scored against the real price after 24h and 7d. Pushes
          (no move) are excluded.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>Model</th>
              {HORIZONS.map((h) => (
                <th key={h} className="num">{h} accuracy</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {models.map(([model, row]) => (
              <tr key={model}>
                <td><strong>{model}</strong></td>
                {HORIZONS.map((h) => {
                  const t = row[h];
                  const acc = accuracy(t);
                  return (
                    <td key={h} className="num">
                      {acc !== null ? (
                        <span className={acc >= 50 ? "pos" : "neg"}>{acc.toFixed(0)}%</span>
                      ) : (
                        <span className="muted">—</span>
                      )}{" "}
                      <span className="muted">({t.correct + t.incorrect})</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Recent signals</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Asset</th>
              <th>Call</th>
              <th className="num">Confidence</th>
              {HORIZONS.map((h) => (
                <th key={h} className="num">{h}</th>
              ))}
              <th>Model</th>
            </tr>
          </thead>
          <tbody>
            {predictions.slice(0, 50).map((p) => (
              <tr key={p.id}>
                <td className="muted">{dateTime(p.created_at)}</td>
                <td><strong>{p.asset}</strong></td>
                <td><span className={`pill ${p.direction}`}>{p.direction}</span></td>
                <td className="num">{pct(Math.max(p.bullish_prob, p.bearish_prob)).replace("+", "")}</td>
                {HORIZONS.map((h) => (
                  <td key={h} className="num"><Outcome ev={evalFor(p, h)} /></td>
                ))}
                <td className="muted">{p.model}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
