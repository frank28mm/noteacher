-- Create long-term submission facts table (authoritative upload + grade snapshot).
-- This mirrors `supabase/schema.sql` but is kept minimal (no RLS/policies here).

create extension if not exists "uuid-ossp";

create table if not exists public.submissions (
  id uuid primary key default uuid_generate_v4(),
  submission_id text unique not null,
  user_id text not null,
  session_id text,
  subject text,
  page_image_urls jsonb not null default '[]'::jsonb,
  proxy_page_image_urls jsonb not null default '[]'::jsonb,
  vision_raw_text text,
  grade_result jsonb not null default '{}'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  last_active_at timestamptz not null default now()
);

create index if not exists submissions_user_id_idx on public.submissions (user_id);
create index if not exists submissions_session_id_idx on public.submissions (session_id);
create index if not exists submissions_created_at_idx on public.submissions (created_at desc);

