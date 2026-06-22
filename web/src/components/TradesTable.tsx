import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { dateTime, money, pct, signClass } from "../lib/format";
import type { NewsItem, Trade } from "../types";
import AssetBadge from "./ui/AssetBadge";
import GlassCard from "./ui/GlassCard";
import Pill from "./ui/Pill";

function parseNews(json?: string | null): NewsItem[] {
  if (!json) return [];
  try {
    const arr = JSON.parse(json);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

type Filter = "all" | "open" | "closed";
const FILTERS: Filter[] = ["all", "open", "closed"];

export default function TradesTable({ trades }: { trades: Trade[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = trades.filter((t) => {
    if (filter === "open") return t.status === "open" || t.status === "submitted";
    if (filter === "closed") return t.status === "closed";
    return true;
  });

  return (
    <GlassCard className="panel">
      <div className="panel-head">
        <h2>All trades — nothing hidden</h2>
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f} className={`chip ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="empty-note">
          {trades.length === 0
            ? "No trades yet. The bot only trades on fresh news with high confidence — check back after a few cycles."
            : "No trades match this filter."}
        </p>
      ) : (
        <div className="scroll-x">
          <div className="trades">
            <div className="trow thead">
              <span>Date</span><span>Asset</span><span>Side</span><span>Status</span>
              <span className="num">Entry</span><span className="num">Exit</span>
              <span className="num">P&amp;L</span><span className="num">P&amp;L %</span>
            </div>
            {filtered.map((t) => {
              const expanded = openId === t.id;
              const news = parseNews(t.prediction?.news_snapshot);
              return (
                <div key={t.id} className="titem">
                  <div className="trow row-click" onClick={() => setOpenId(expanded ? null : t.id)}>
                    <span className="muted">{dateTime(t.created_at)}</span>
                    <span><AssetBadge symbol={t.asset} /></span>
                    <span><Pill kind={t.side}>{t.side}</Pill></span>
                    <span><Pill kind={t.status}>{t.status}</Pill></span>
                    <span className="num mono">{money(t.entry_price)}</span>
                    <span className="num mono">{money(t.exit_price)}</span>
                    <span className={`num mono ${signClass(t.pnl)}`}>{t.pnl != null ? money(t.pnl) : "—"}</span>
                    <span className={`num mono ${signClass(t.pnl_pct)}`}>{t.pnl_pct != null ? pct(t.pnl_pct) : "—"}</span>
                  </div>
                  <AnimatePresence initial={false}>
                    {expanded && (
                      <motion.div
                        className="expand-wrap"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.28, ease: "easeOut" }}
                      >
                        <div className="expand-inner">
                          <div className="rationale">
                            <strong>Why{t.model ? ` (${t.model})` : ""}:</strong> {t.rationale || "—"}
                          </div>
                          {t.close_reason && (
                            <div className="muted" style={{ marginTop: 6 }}>Closed via: {t.close_reason}</div>
                          )}
                          {news.length > 0 && (
                            <>
                              <div className="muted" style={{ marginTop: 10 }}>News the signal was based on:</div>
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
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
