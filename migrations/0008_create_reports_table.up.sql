-- Generated reports (features_json is the deterministic core; narrative is optional).

create table if not exists public.reports (
  report_id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  params jsonb not null default '{}'::jsonb,
  features_json jsonb not null default '{}'::jsonb,
  narrative_json jsonb,
  narrative_md text,
  evidence_refs jsonb not null default '[]'::jsonb,
  report_version text,
  taxonomy_version text,
  classifier_version text,
  created_at timestamptz not null default now()
);

create index if not exists reports_user_created_idx
  on public.reports (user_id, created_at desc);

