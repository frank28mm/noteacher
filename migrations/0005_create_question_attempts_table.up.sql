-- Derived per-question facts (including correct items) for report denominators.

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

