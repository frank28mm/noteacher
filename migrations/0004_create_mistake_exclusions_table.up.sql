-- Mistake "deletion" semantics: exclusions affect reports/statistics only, not historical facts.

create extension if not exists "uuid-ossp";

create table if not exists public.mistake_exclusions (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  item_id text not null,
  reason text,
  excluded_at timestamptz not null default now(),
  unique (user_id, submission_id, item_id)
);

create index if not exists mistake_exclusions_user_id_idx on public.mistake_exclusions (user_id);
create index if not exists mistake_exclusions_submission_id_idx on public.mistake_exclusions (submission_id);

