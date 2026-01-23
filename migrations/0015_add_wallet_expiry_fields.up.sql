alter table public.user_wallets
  add column if not exists bt_subscription_active bigint not null default 0,
  add column if not exists bt_subscription_expired bigint not null default 0,
  add column if not exists last_expiry_check_at timestamptz;
