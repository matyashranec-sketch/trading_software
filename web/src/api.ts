import { supabase } from "./supabase";
import type { EquitySnapshot, Prediction, Trade } from "./types";

export async function fetchTrades(): Promise<Trade[]> {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from("trades")
    .select("*, prediction:predictions(*)")
    .order("created_at", { ascending: false })
    .limit(300);
  if (error) throw error;
  return (data ?? []) as Trade[];
}

export async function fetchEquity(): Promise<EquitySnapshot[]> {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from("equity_snapshots")
    .select("*")
    .order("ts", { ascending: true })
    .limit(1000);
  if (error) throw error;
  return (data ?? []) as EquitySnapshot[];
}

export async function fetchPredictions(): Promise<Prediction[]> {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from("predictions")
    .select("*, evaluations(*)")
    .order("created_at", { ascending: false })
    .limit(300);
  if (error) throw error;
  return (data ?? []) as Prediction[];
}
