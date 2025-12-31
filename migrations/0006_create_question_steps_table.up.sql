-- Derived per-step facts for process diagnosis (e.g., calculation habit).

create table if not exists public.question_steps (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  item_id text not null,
  step_index int not null,

  created_at timestamptz not null,
  subject text,

  verdict text,
  severity text,

  expected text,
  observed text,

  diagnosis_codes jsonb not null default '[]'::jsonb,
  step_raw jsonb not null default '{}'::jsonb,

  extract_version text,
  diagnosis_version text,

  updated_at timestamptz not null default now(),

  unique (user_id, submission_id, item_id, step_index)
);

create index if not exists question_steps_user_created_idx
  on public.question_steps (user_id, created_at desc);

create index if not exists question_steps_user_severity_idx
  on public.question_steps (user_id, severity);

create index if not exists question_steps_diagnosis_codes_gin
  on public.question_steps using gin (diagnosis_codes);

