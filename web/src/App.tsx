import { useCallback, useEffect, useState } from "react";
import { fetchEquity, fetchPredictions, fetchTrades } from "./api";
import Dashboard from "./components/Dashboard";
import Leaderboard from "./components/Leaderboard";
import Setup from "./components/Setup";
import TradesTable from "./components/TradesTable";
import Card from "./components/ui/Card";
import LoadingSkeleton from "./components/ui/Skeleton";
import { dateTime } from "./lib/format";
import { isConfigured } from "./supabase";
import type { EquitySnapshot, Prediction, Trade } from "./types";

type Tab = "dashboard" | "trades" | "signals";
const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "trades", label: "Trades" },
  { id: "signals", label: "Signals" },
];

function Header({
  updated,
  onRefresh,
  refreshing,
}: {
  updated?: Date | null;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  return (
    <Card className="header">
      <div className="brand">
        <h1>Order-Flow <span className="mark">Trading Bot</span></h1>
        <span className="tag">
          A deterministic strategy scores a strict order-flow confluence checklist; an LLM
          confirms each setup before it trades — long or short. Every trade — winners and
          losers — stays public, with the exact checklist that drove it.
        </span>
      </div>
      <div className="header-right">
        <span className="badge"><span className="dot" /> Paper trading</span>
        {onRefresh && (
          <div className="toolbar">
            {updated && <span>Updated {dateTime(updated.toISOString())}</span>}
            <button className="btn" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquitySnapshot[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setRefreshing(true);
      const [t, e, p] = await Promise.all([fetchTrades(), fetchEquity(), fetchPredictions()]);
      setTrades(t);
      setEquity(e);
      setPredictions(p);
      setUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
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
        <div style={{ marginTop: 18 }}>
          <Setup />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <Header updated={updated} onRefresh={load} refreshing={refreshing} />

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
        <LoadingSkeleton />
      ) : (
        <div key={tab} className="fade-in">
          {tab === "dashboard" ? (
            <Dashboard equity={equity} trades={trades} />
          ) : tab === "trades" ? (
            <TradesTable trades={trades} />
          ) : (
            <Leaderboard predictions={predictions} />
          )}
        </div>
      )}
    </div>
  );
}
