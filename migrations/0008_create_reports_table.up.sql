-- Generated reports (stats/content are stable output; report_job_id links back to the job).

create table if not exists public.reports (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  report_job_id uuid references public.report_jobs(id) on delete set null,
  title text,
  period_from date,
  period_to date,
  used_submission_ids jsonb not null default '[]'::jsonb,
  exclusions_snapshot jsonb not null default '[]'::jsonb,
  stats jsonb not null default '{}'::jsonb,
  content text, -- markdown / rich text
  created_at timestamptz not null default now()
);

create index if not exists reports_user_created_idx
  on public.reports (user_id, created_at desc);
