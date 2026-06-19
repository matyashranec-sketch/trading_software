export type Direction = "bullish" | "bearish";

export interface NewsItem {
  headline: string;
  summary: string;
  source: string;
  url: string;
  datetime: number;
}

export interface Evaluation {
  id: number;
  prediction_id: number;
  horizon: string;
  target_eval_time: string;
  status: string;
  evaluated_at: string | null;
  price_at_eval: number | null;
  actual_direction: string | null;
  is_correct: boolean | null;
}

export interface Prediction {
  id: number;
  created_at: string;
  asset: string;
  model: string;
  direction: Direction;
  bullish_prob: number;
  bearish_prob: number;
  price_at_prediction: number;
  rationale: string;
  news_snapshot: string;
  evaluations?: Evaluation[];
}

export interface Trade {
  id: number;
  created_at: string;
  asset: string;
  side: "buy" | "sell";
  status: "submitted" | "open" | "closed" | "canceled";
  qty: number | null;
  notional: number | null;
  entry_price: number | null;
  alpaca_order_id: string | null;
  model: string;
  rationale: string;
  stop_price: number | null;
  take_profit: number | null;
  closed_at: string | null;
  exit_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  close_reason: string | null;
  prediction_id: number | null;
  prediction?: Prediction | null;
}

export interface EquitySnapshot {
  id: number;
  ts: string;
  equity: number;
  cash: number;
  buying_power: number;
}
