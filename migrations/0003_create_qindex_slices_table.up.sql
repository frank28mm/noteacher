-- Persist per-question slice refs with TTL, so chat can still locate slices after Redis loss.

create extension if not exists "uuid-ossp";

create table if not exists public.qindex_slices (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  session_id text,
  question_number text not null,
  image_refs jsonb not null default '{}'::jsonb,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (submission_id, question_number)
);

create index if not exists qindex_slices_user_id_idx on public.qindex_slices (user_id);
create index if not exists qindex_slices_session_id_idx on public.qindex_slices (session_id);
create index if not exists qindex_slices_expires_at_idx on public.qindex_slices (expires_at);

