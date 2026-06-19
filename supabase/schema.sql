-- Supabase schema for the trading bot.
--
-- Run this once in the Supabase SQL editor. It creates the tables (matching the
-- SQLAlchemy models in app/models.py) and locks them down with Row Level
-- Security so the public anon key can ONLY read. The bot writes using the full
-- Postgres connection string (table owner -> bypasses RLS).
--
-- Safe to run after `python -m app.cli initdb` too: the CREATEs are IF NOT
-- EXISTS and only the RLS/grants below will be (re)applied.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
create table if not exists predictions (
    id                  bigserial primary key,
    created_at          timestamp not null default (now() at time zone 'utc'),
    asset               varchar(16) not null,
    model               varchar(64) not null,
    direction           varchar(8)  not null,
    bullish_prob        double precision not null,
    bearish_prob        double precision not null,
    price_at_prediction double precision not null,
    rationale           text not null default '',
    news_snapshot       text not null default '[]'
);
create index if not exists ix_predictions_created_at on predictions (created_at);
create index if not exists ix_predictions_asset      on predictions (asset);
create index if not exists ix_predictions_model      on predictions (model);

create table if not exists evaluations (
    id               bigserial primary key,
    prediction_id    bigint not null references predictions (id) on delete cascade,
    horizon          varchar(8)  not null,
    target_eval_time timestamp not null,
    status           varchar(16) not null default 'pending',
    evaluated_at     timestamp,
    price_at_eval    double precision,
    actual_direction varchar(8),
    is_correct       boolean
);
create index if not exists ix_evaluations_prediction_id    on evaluations (prediction_id);
create index if not exists ix_evaluations_horizon          on evaluations (horizon);
create index if not exists ix_evaluations_target_eval_time on evaluations (target_eval_time);
create index if not exists ix_evaluations_status           on evaluations (status);

create table if not exists trades (
    id              bigserial primary key,
    created_at      timestamp not null default (now() at time zone 'utc'),
    asset           varchar(16) not null,
    side            varchar(8)  not null,
    status          varchar(16) not null default 'submitted',
    qty             double precision,
    notional        double precision,
    entry_price     double precision,
    alpaca_order_id varchar(64),
    model           varchar(64) not null default '',
    rationale       text not null default '',
    stop_price      double precision,
    take_profit     double precision,
    closed_at       timestamp,
    exit_price      double precision,
    pnl             double precision,
    pnl_pct         double precision,
    close_reason    varchar(16),
    prediction_id   bigint references predictions (id)
);
create index if not exists ix_trades_created_at      on trades (created_at);
create index if not exists ix_trades_asset           on trades (asset);
create index if not exists ix_trades_status          on trades (status);
create index if not exists ix_trades_alpaca_order_id on trades (alpaca_order_id);
create index if not exists ix_trades_prediction_id   on trades (prediction_id);

create table if not exists equity_snapshots (
    id           bigserial primary key,
    ts           timestamp not null default (now() at time zone 'utc'),
    equity       double precision not null,
    cash         double precision not null,
    buying_power double precision not null
);
create index if not exists ix_equity_snapshots_ts on equity_snapshots (ts);

-- ---------------------------------------------------------------------------
-- Row Level Security: public (anon) read-only; writes only via the bot's
-- privileged Postgres connection.
-- ---------------------------------------------------------------------------
alter table predictions      enable row level security;
alter table evaluations      enable row level security;
alter table trades           enable row level security;
alter table equity_snapshots enable row level security;

drop policy if exists "public read predictions"      on predictions;
drop policy if exists "public read evaluations"      on evaluations;
drop policy if exists "public read trades"           on trades;
drop policy if exists "public read equity_snapshots" on equity_snapshots;

create policy "public read predictions"      on predictions      for select using (true);
create policy "public read evaluations"      on evaluations      for select using (true);
create policy "public read trades"           on trades           for select using (true);
create policy "public read equity_snapshots" on equity_snapshots for select using (true);

grant usage on schema public to anon, authenticated;
grant select on predictions, evaluations, trades, equity_snapshots to anon, authenticated;
