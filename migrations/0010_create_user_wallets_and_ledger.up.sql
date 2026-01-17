create extension if not exists "uuid-ossp";

create table if not exists public.user_wallets (
  user_id text primary key references public.users(user_id) on delete cascade,
  bt_trial bigint not null default 0,
  bt_subscription bigint not null default 0,
  bt_report_reserve bigint not null default 0,
  report_coupons int not null default 0,
  trial_expires_at timestamptz,
  plan_tier text,
  data_retention_tier text,
  updated_at timestamptz not null default now()
);

create table if not exists public.usage_ledger (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  request_id text,
  idempotency_key text,
  endpoint text not null,
  stage text,
  model text,
  prompt_tokens int,
  completion_tokens int,
  total_tokens int,
  bt_delta bigint not null default 0,
  bt_trial_delta bigint not null default 0,
  bt_subscription_delta bigint not null default 0,
  bt_report_reserve_delta bigint not null default 0,
  report_coupons_delta int not null default 0,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.usage_ledger
  add constraint usage_ledger_user_idempotency_unique unique (user_id, idempotency_key);

create index if not exists idx_usage_ledger_user_created on public.usage_ledger (user_id, created_at desc);
