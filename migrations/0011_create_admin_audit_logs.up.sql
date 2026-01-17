create extension if not exists "uuid-ossp";

create table if not exists public.admin_audit_logs (
  id uuid primary key default uuid_generate_v4(),
  actor text,
  action text not null,
  target_type text,
  target_id text,
  payload jsonb not null default '{}'::jsonb,
  request_id text,
  ip text,
  user_agent text,
  created_at timestamptz not null default now()
);

create index if not exists idx_admin_audit_logs_created on public.admin_audit_logs (created_at desc);
create index if not exists idx_admin_audit_logs_action on public.admin_audit_logs (action);

