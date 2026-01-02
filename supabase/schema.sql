-- 初始化作业检查大师的基础数据结构
-- 在 Supabase 控制台 -> SQL Editor 中粘贴并运行本脚本

-- 1) 需要的扩展（用于生成 UUID）
create extension if not exists "uuid-ossp";

-- 2) 作业表（示例）
create table if not exists public.homeworks (
  id uuid primary key default uuid_generate_v4(),
  title text not null,
  description text,
  due_date timestamptz,
  created_at timestamptz not null default now()
);

-- 3) 开启 RLS，并设置基础访问策略
alter table public.homeworks enable row level security;

-- 允许匿名读取（方便前期用 anon key 测试；上线可改为仅 authenticated）
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'homeworks' and policyname = 'homeworks_select_anon'
  ) then
    create policy homeworks_select_anon on public.homeworks
      for select
      to anon
      using (true);
  end if;
end$$;

-- 允许已认证用户插入（示例，可按需要调整）
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'homeworks' and policyname = 'homeworks_insert_authenticated'
  ) then
    create policy homeworks_insert_authenticated on public.homeworks
      for insert
      to authenticated
      with check (true);
  end if;
end$$;

-- 4) 示例数据（可选）
insert into public.homeworks (title, description, due_date)
values
  ('数学作业', '章节 3：函数与导数', now() + interval '7 days'),
  ('英语作业', '背诵第 10 课词汇表', now() + interval '3 days')
on conflict do nothing;

-- 运行完成后，可在前端使用 anon key 读取：
-- GET https://<project>.supabase.co/rest/v1/homeworks?select=*

-- =========================
-- 用户隔离的上传记录（开发期）
-- =========================
create table if not exists public.user_uploads (
  id uuid primary key default uuid_generate_v4(),
  upload_id text unique not null,
  user_id text not null,
  session_id text,
  filename text,
  content_type text,
  size_bytes bigint,
  page_image_urls jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.user_uploads enable row level security;

-- 开发期：允许匿名读取/写入（便于联调）；上线后应改为 authenticated + auth.uid() 约束
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'user_uploads' and policyname = 'user_uploads_select_anon'
  ) then
    create policy user_uploads_select_anon on public.user_uploads
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'user_uploads' and policyname = 'user_uploads_insert_anon'
  ) then
    create policy user_uploads_insert_anon on public.user_uploads
      for insert
      to anon
      with check (true);
  end if;
end$$;

-- =========================
-- Submission / 报告（产品化目标；开发期可先建表）
-- 说明：当前后端代码使用 public.user_uploads 作为 upload_id 的反查来源。
-- 下列 submissions/mistake_exclusions/report_* 为后续“长期留存/学业报告/错题排除”准备。
-- =========================

create table if not exists public.submissions (
  id uuid primary key default uuid_generate_v4(),
  submission_id text unique not null, -- 建议与 upload_id 同值（一次上传=一次 Submission）
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

alter table public.submissions enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'submissions' and policyname = 'submissions_select_anon'
  ) then
    create policy submissions_select_anon on public.submissions
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'submissions' and policyname = 'submissions_insert_anon'
  ) then
    create policy submissions_insert_anon on public.submissions
      for insert
      to anon
      with check (true);
  end if;
end$$;

-- 开发期：允许匿名更新（后端会更新 session_id/last_active_at/grade_result 等字段）
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'submissions' and policyname = 'submissions_update_anon'
  ) then
    create policy submissions_update_anon on public.submissions
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

-- 切片索引：用于在 Redis 丢失/重启后仍可在 7 天内找回切片（按 question_number 粒度）
create table if not exists public.qindex_slices (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  session_id text,
  question_number text not null,
  image_refs jsonb not null default '{}'::jsonb, -- 结构与 qindex.questions[qn] 一致（含 pages/slice_image_urls/regions）
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (submission_id, question_number)
);

alter table public.qindex_slices enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'qindex_slices' and policyname = 'qindex_slices_select_anon'
  ) then
    create policy qindex_slices_select_anon on public.qindex_slices
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'qindex_slices' and policyname = 'qindex_slices_insert_anon'
  ) then
    create policy qindex_slices_insert_anon on public.qindex_slices
      for insert
      to anon
      with check (true);
  end if;
end$$;

-- 开发期：允许匿名更新（worker 会 upsert 切片索引/刷新 expires_at）
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'qindex_slices' and policyname = 'qindex_slices_update_anon'
  ) then
    create policy qindex_slices_update_anon on public.qindex_slices
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

-- 错题“删除”语义：只影响统计/报告（排除），不改 submission 的历史事实
create table if not exists public.mistake_exclusions (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  submission_id text not null,
  item_id text not null,
  reason text,
  excluded_at timestamptz not null default now(),
  unique (user_id, submission_id, item_id)
);

alter table public.mistake_exclusions enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'mistake_exclusions' and policyname = 'mistake_exclusions_select_anon'
  ) then
    create policy mistake_exclusions_select_anon on public.mistake_exclusions
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'mistake_exclusions' and policyname = 'mistake_exclusions_insert_anon'
  ) then
    create policy mistake_exclusions_insert_anon on public.mistake_exclusions
      for insert
      to anon
      with check (true);
  end if;
end$$;

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

alter table public.question_attempts enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_attempts' and policyname = 'question_attempts_select_anon'
  ) then
    create policy question_attempts_select_anon on public.question_attempts
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_attempts' and policyname = 'question_attempts_insert_anon'
  ) then
    create policy question_attempts_insert_anon on public.question_attempts
      for insert
      to anon
      with check (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_attempts' and policyname = 'question_attempts_update_anon'
  ) then
    create policy question_attempts_update_anon on public.question_attempts
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

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

alter table public.question_steps enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_steps' and policyname = 'question_steps_select_anon'
  ) then
    create policy question_steps_select_anon on public.question_steps
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_steps' and policyname = 'question_steps_insert_anon'
  ) then
    create policy question_steps_insert_anon on public.question_steps
      for insert
      to anon
      with check (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'question_steps' and policyname = 'question_steps_update_anon'
  ) then
    create policy question_steps_update_anon on public.question_steps
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

create index if not exists question_steps_user_created_idx
  on public.question_steps (user_id, created_at desc);

create index if not exists question_steps_user_severity_idx
  on public.question_steps (user_id, severity);

create index if not exists question_steps_diagnosis_codes_gin
  on public.question_steps using gin (diagnosis_codes);

-- 报告：异步生成（可下载/可查看历史报告）
create table if not exists public.report_jobs (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  status text not null default 'queued', -- queued/pending/running/done/failed (pending kept for compatibility)
  params jsonb not null default '{}'::jsonb, -- {from,to,subject,...}
  error text,
  last_error text,
  attempt_count int not null default 0,
  locked_at timestamptz,
  locked_by text,
  report_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.report_jobs enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'report_jobs' and policyname = 'report_jobs_select_anon'
  ) then
    create policy report_jobs_select_anon on public.report_jobs
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'report_jobs' and policyname = 'report_jobs_insert_anon'
  ) then
    create policy report_jobs_insert_anon on public.report_jobs
      for insert
      to anon
      with check (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'report_jobs' and policyname = 'report_jobs_update_anon'
  ) then
    create policy report_jobs_update_anon on public.report_jobs
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

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

alter table public.reports enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'reports' and policyname = 'reports_select_anon'
  ) then
    create policy reports_select_anon on public.reports
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'reports' and policyname = 'reports_insert_anon'
  ) then
    create policy reports_insert_anon on public.reports
      for insert
      to anon
      with check (true);
  end if;
end$$;
