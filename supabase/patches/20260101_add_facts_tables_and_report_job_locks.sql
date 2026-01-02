-- Incremental schema patch (no DROP SCHEMA).
-- Apply via Supabase Dashboard -> SQL Editor.

create extension if not exists "uuid-ossp";

-- 1) Derived facts tables (for report denominators & process diagnosis)
create table if not exists public.question_attempts (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  item_id text not null,

  created_at timestamptz not null,
  subject text,

  question_number text,
  question_idx int,
  verdict text,

  knowledge_tags jsonb not null default '[]'::jsonb,
  knowledge_tags_norm jsonb not null default '[]'::jsonb,
  question_type text,
  difficulty text,

  severity text,
  warnings jsonb not null default '[]'::jsonb,

  question_raw jsonb not null default '{}'::jsonb,

  extract_version text,
  taxonomy_version text,
  classifier_version text,

  updated_at timestamptz not null default now(),

  unique (user_id, submission_id, item_id)
);

create index if not exists question_attempts_user_created_idx
  on public.question_attempts (user_id, created_at desc);

create index if not exists question_attempts_user_subject_created_idx
  on public.question_attempts (user_id, subject, created_at desc);

create index if not exists question_attempts_user_type_idx
  on public.question_attempts (user_id, question_type);

create index if not exists question_attempts_user_difficulty_idx
  on public.question_attempts (user_id, difficulty);

create index if not exists question_attempts_knowledge_tags_norm_gin
  on public.question_attempts using gin (knowledge_tags_norm);


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


-- 2) report_jobs: add lock fields + report_id for worker lifecycle
alter table public.report_jobs
  add column if not exists locked_at timestamptz,
  add column if not exists locked_by text,
  add column if not exists attempt_count int not null default 0,
  add column if not exists last_error text,
  add column if not exists report_id uuid;

-- Make sure the default matches current code expectation (queued).
alter table public.report_jobs
  alter column status set default 'queued';

create index if not exists report_jobs_status_created_idx
  on public.report_jobs (status, created_at asc);

