-- BT 额度授予记录表（用于追踪每笔额度的过期时间）

create table if not exists public.bt_grants (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  bt_amount int not null,
  grant_type text not null,
  expires_at timestamptz not null,
  is_expired boolean not null default false,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  created_from text,
  reference_id text,
  meta jsonb not null default '{}'::jsonb
);

create index if not exists idx_bt_grants_user_expires on public.bt_grants (user_id, expires_at);
create index if not exists idx_bt_grants_expires_unexpired on public.bt_grants (expires_at) where is_expired = false;
create index if not exists idx_bt_grants_created on public.bt_grants (created_at desc);
