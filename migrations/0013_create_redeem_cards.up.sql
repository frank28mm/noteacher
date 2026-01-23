-- Redeem cards (兑换码/充值卡) for BT credits, report coupons, or subscription time.

create table if not exists public.redeem_cards (
  id uuid primary key default uuid_generate_v4(),
  code text unique not null,
  card_type text not null default 'trial',        -- trial | subscription | report_coupon
  bt_amount bigint not null default 0,            -- BT credits to add
  report_coupons int not null default 0,          -- report coupons to add
  plan_tier text,                                 -- subscription tier (e.g. 'basic', 'pro')
  plan_days int,                                  -- subscription days to add
  status text not null default 'active',          -- active | redeemed | expired | disabled
  redeemed_by text,                               -- user_id who redeemed
  redeemed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  created_by text,                                -- admin who created
  batch_id text,                                  -- for batch generation tracking
  notes text
);

create index if not exists idx_redeem_cards_code on public.redeem_cards (code);
create index if not exists idx_redeem_cards_status on public.redeem_cards (status);
create index if not exists idx_redeem_cards_redeemed_by on public.redeem_cards (redeemed_by);
create index if not exists idx_redeem_cards_created on public.redeem_cards (created_at desc);
