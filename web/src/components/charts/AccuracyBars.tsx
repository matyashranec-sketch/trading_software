import type { Prediction } from "../../types";

const HORIZONS = ["24h", "7d"];
type Tally = { correct: number; incorrect: number };
const emptyRow = (): Record<string, Tally> => ({
  "24h": { correct: 0, incorrect: 0 },
  "7d": { correct: 0, incorrect: 0 },
});

export default function AccuracyBars({ predictions }: { predictions: Prediction[] }) {
  const byModel = new Map<string, Record<string, Tally>>();
  for (const p of predictions) {
    const row = byModel.get(p.model) ?? emptyRow();
    for (const ev of p.evaluations ?? []) {
      const cell = row[ev.horizon];
      if (!cell) continue;
      if (ev.status !== "evaluated" || ev.is_correct === null) continue;
      if (ev.is_correct) cell.correct++;
      else cell.incorrect++;
    }
    byModel.set(p.model, row);
  }

  const rows = [...byModel.entries()];
  const anyDecided = rows.some(([, r]) =>
    HORIZONS.some((h) => {
      const c = r[h];
      return c ? c.correct + c.incorrect > 0 : false;
    }),
  );

  if (!rows.length || !anyDecided) {
    return (
      <div className="chart-empty" style={{ height: 150 }}>
        Accuracy appears once signals are scored (after 24h / 7d).
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {rows.map(([model, r]) => (
        <div key={model}>
          <div style={{ fontWeight: 650, marginBottom: 8, fontSize: 14 }}>{model}</div>
          {HORIZONS.map((h) => {
            const t = r[h] ?? { correct: 0, incorrect: 0 };
            const decided = t.correct + t.incorrect;
            const acc = decided ? (t.correct / decided) * 100 : null;
            const color = acc != null && acc >= 50 ? "var(--pos)" : "var(--neg)";
            return (
              <div key={h} style={{ display: "flex", alignItems: "center", gap: 10, margin: "7px 0" }}>
                <span className="muted" style={{ width: 28, fontSize: 12 }}>{h}</span>
                <div style={{ flex: 1, height: 6, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                  {acc != null && (
                    <div
                      style={{ width: `${acc}%`, height: "100%", background: color, borderRadius: 999, transition: "width .3s ease" }}
                    />
                  )}
                </div>
                <span
                  className="mono"
                  style={{ width: 84, textAlign: "right", fontSize: 12.5, color: acc != null ? color : "var(--muted)" }}
                >
                  {acc != null ? `${acc.toFixed(0)}%` : "—"} <span className="faint">({decided})</span>
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
