-- Report generation jobs (async, restartable).

create table if not exists public.report_jobs (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  params jsonb not null default '{}'::jsonb,
  status text not null default 'pending', -- pending/running/done/failed
  attempt int not null default 0,
  locked_at timestamptz,
  locked_by text,
  error text,
  report_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists report_jobs_user_created_idx
  on public.report_jobs (user_id, created_at desc);

create index if not exists report_jobs_status_created_idx
  on public.report_jobs (status, created_at asc);

