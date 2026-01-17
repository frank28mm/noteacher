create extension if not exists "uuid-ossp";

create table if not exists public.users (
  user_id text primary key default uuid_generate_v4()::text,
  phone text unique not null,
  nickname text,
  created_at timestamptz not null default now(),
  last_login_at timestamptz
);

create index if not exists idx_users_created_at on public.users (created_at desc);

