alter table public.user_wallets
  drop column if exists last_expiry_check_at,
  drop column if exists bt_subscription_expired,
  drop column if exists bt_subscription_active;
