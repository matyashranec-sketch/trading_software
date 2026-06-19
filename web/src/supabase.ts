import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

/** Whether the public Supabase env vars are present. */
export const isConfigured = Boolean(url && anonKey);

/**
 * Read-only Supabase client. The anon key is public on purpose — Row Level
 * Security on the database makes it read-only, so it is safe to ship.
 */
export const supabase = isConfigured ? createClient(url!, anonKey!) : null;
