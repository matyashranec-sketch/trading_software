import { Fragment, useState } from "react";
import { dateTime, money, pct, signClass } from "../lib/format";
import type { NewsItem, Trade } from "../types";

function parseNews(json?: string | null): NewsItem[] {
  if (!json) return [];
  try {
    const arr = JSON.parse(json);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export default function TradesTable({ trades }: { trades: Trade[] }) {
  const [openId, setOpenId] = useState<number | null>(null);

  if (!trades.length) {
    return (
      <div className="panel">
        <p className="muted">
          No trades yet. The bot only trades on fresh news with high confidence —
          check back after a few runs.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>All trades ({trades.length}) — nothing hidden</h2>
      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Asset</th>
            <th>Side</th>
            <th>Status</th>
            <th className="num">Entry</th>
            <th className="num">Exit</th>
            <th className="num">P&amp;L</th>
            <th className="num">P&amp;L %</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const news = parseNews(t.prediction?.news_snapshot);
            const expanded = openId === t.id;
            return (
              <Fragment key={t.id}>
                <tr className="clickable" onClick={() => setOpenId(expanded ? null : t.id)}>
                  <td className="muted">{dateTime(t.created_at)}</td>
                  <td><strong>{t.asset}</strong></td>
                  <td><span className={`pill ${t.side}`}>{t.side}</span></td>
                  <td><span className={`pill ${t.status}`}>{t.status}</span></td>
                  <td className="num">{money(t.entry_price)}</td>
                  <td className="num">{money(t.exit_price)}</td>
                  <td className={`num ${signClass(t.pnl)}`}>{t.pnl != null ? money(t.pnl) : "—"}</td>
                  <td className={`num ${signClass(t.pnl_pct)}`}>{t.pnl_pct != null ? pct(t.pnl_pct) : "—"}</td>
                </tr>
                {expanded && (
                  <tr className="expand">
                    <td colSpan={8}>
                      <div className="rationale">
                        <strong>Why{t.model ? ` (${t.model})` : ""}:</strong>{" "}
                        {t.rationale || "—"}
                      </div>
                      {t.close_reason && (
                        <div className="muted" style={{ marginTop: 6 }}>
                          Closed via: {t.close_reason}
                        </div>
                      )}
                      {news.length > 0 && (
                        <>
                          <div className="muted" style={{ marginTop: 10 }}>
                            News the signal was based on:
                          </div>
                          <ul className="news-list">
                            {news.slice(0, 8).map((n, i) => (
                              <li key={i}>
                                {n.url ? (
                                  <a href={n.url} target="_blank" rel="noreferrer">{n.headline}</a>
                                ) : (
                                  n.headline
                                )}
                                {n.source ? ` — ${n.source}` : ""}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
