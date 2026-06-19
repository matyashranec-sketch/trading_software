import { useCallback, useEffect, useState } from "react";
import { fetchEquity, fetchPredictions, fetchTrades } from "./api";
import Dashboard from "./components/Dashboard";
import Leaderboard from "./components/Leaderboard";
import Setup from "./components/Setup";
import TradesTable from "./components/TradesTable";
import { dateTime } from "./lib/format";
import { isConfigured } from "./supabase";
import type { EquitySnapshot, Prediction, Trade } from "./types";

type Tab = "dashboard" | "trades" | "signals";
const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "trades", label: "Trades" },
  { id: "signals", label: "Signals" },
];

function Header({ updated, onRefresh }: { updated?: Date | null; onRefresh?: () => void }) {
  return (
    <header className="header">
      <div className="brand">
        <h1>News-Driven Trading Bot</h1>
        <span className="tag">
          An AI reads fresh news every ~2 hours and trades only when it is
          confident. Every trade — winners and losers — stays public, with the
          reasoning and news that drove it.
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        <span className="badge">● Paper trading</span>
        {onRefresh && (
          <div className="toolbar">
            {updated && <span>Updated {dateTime(updated.toISOString())}</span>}
            <button className="btn" onClick={onRefresh}>Refresh</button>
          </div>
        )}
      </div>
    </header>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquitySnapshot[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [t, e, p] = await Promise.all([fetchTrades(), fetchEquity(), fetchPredictions()]);
      setTrades(t);
      setEquity(e);
      setPredictions(p);
      setUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isConfigured) {
      setLoading(false);
      return;
    }
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  if (!isConfigured) {
    return (
      <div className="app">
        <Header />
        <Setup />
      </div>
    );
  }

  return (
    <div className="app">
      <Header updated={updated} onRefresh={load} />
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {error && <div className="error">Couldn’t load data: {error}</div>}

      {loading ? (
        <div className="loading">Loading…</div>
      ) : tab === "dashboard" ? (
        <Dashboard equity={equity} trades={trades} />
      ) : tab === "trades" ? (
        <TradesTable trades={trades} />
      ) : (
        <Leaderboard predictions={predictions} />
      )}
    </div>
  );
}
