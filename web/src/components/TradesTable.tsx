import { useState } from "react";
import { dateTime, money, pct, signClass } from "../lib/format";
import type { Trade } from "../types";
import AssetBadge from "./ui/AssetBadge";
import Card from "./ui/Card";
import Pill from "./ui/Pill";

interface Confluence {
  passed: boolean;
  direction: string;
  score: number;
  max_score: number;
  checks: Record<string, boolean>;
  stop: number | null;
  target: number | null;
}

function parseConfluence(json?: string | null): Confluence | null {
  if (!json) return null;
  try {
    const o = JSON.parse(json);
    return o && typeof o === "object" && o.checks ? (o as Confluence) : null;
  } catch {
    return null;
  }
}

const sideLabel = (side: string) => (side === "buy" ? "long" : "short");

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
    <Card className="panel">
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
            ? "No trades yet. The bot only fires when the order-flow confluence checklist passes — check back after a few cycles."
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
              const conf = parseConfluence(t.prediction?.news_snapshot);
              return (
                <div key={t.id} className="titem">
                  <div className="trow row-click" onClick={() => setOpenId(expanded ? null : t.id)}>
                    <span className="muted">{dateTime(t.created_at)}</span>
                    <span><AssetBadge symbol={t.asset} /></span>
                    <span><Pill kind={t.side}>{sideLabel(t.side)}</Pill></span>
                    <span><Pill kind={t.status}>{t.status}</Pill></span>
                    <span className="num mono">{money(t.entry_price)}</span>
                    <span className="num mono">{money(t.exit_price)}</span>
                    <span className={`num mono ${signClass(t.pnl)}`}>{t.pnl != null ? money(t.pnl) : "—"}</span>
                    <span className={`num mono ${signClass(t.pnl_pct)}`}>{t.pnl_pct != null ? pct(t.pnl_pct) : "—"}</span>
                  </div>
                  {expanded && (
                    <div className="expand-inner">
                      <div className="rationale">
                        <strong>Why{t.model ? ` (${t.model})` : ""}:</strong> {t.rationale || "—"}
                      </div>
                      {conf && (
                        <>
                          <div className="muted" style={{ marginTop: 10 }}>
                            Confluence checklist — {conf.score}/{conf.max_score} passed
                          </div>
                          <div className="checks">
                            {Object.entries(conf.checks).map(([k, v]) => (
                              <span key={k} className="check" style={{ color: v ? "var(--pos)" : "var(--neg)" }}>
                                {v ? "✓" : "✗"} {k}
                              </span>
                            ))}
                          </div>
                          <div className="muted" style={{ marginTop: 8 }}>
                            Stop <span className="mono">{money(conf.stop)}</span>
                            {" · "}Target <span className="mono">{money(conf.target)}</span>
                          </div>
                        </>
                      )}
                      {t.close_reason && (
                        <div className="muted" style={{ marginTop: 8 }}>Closed via: {t.close_reason}</div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}
