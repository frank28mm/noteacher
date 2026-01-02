-- Enable RLS + dev-time anon policies for derived facts tables
-- and allow report_jobs UPDATE for the report worker.
--
-- Apply via Supabase Dashboard -> SQL Editor.
-- NOTE: This is permissive for dev/testing. Production should tighten policies and/or use service role.

-- question_attempts
alter table if exists public.question_attempts enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_attempts' and policyname='question_attempts_select_anon'
  ) then
    create policy question_attempts_select_anon on public.question_attempts
      for select to anon using (true);
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_attempts' and policyname='question_attempts_insert_anon'
  ) then
    create policy question_attempts_insert_anon on public.question_attempts
      for insert to anon with check (true);
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_attempts' and policyname='question_attempts_update_anon'
  ) then
    create policy question_attempts_update_anon on public.question_attempts
      for update to anon using (true) with check (true);
  end if;
end$$;

-- question_steps
alter table if exists public.question_steps enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_steps' and policyname='question_steps_select_anon'
  ) then
    create policy question_steps_select_anon on public.question_steps
      for select to anon using (true);
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_steps' and policyname='question_steps_insert_anon'
  ) then
    create policy question_steps_insert_anon on public.question_steps
      for insert to anon with check (true);
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='question_steps' and policyname='question_steps_update_anon'
  ) then
    create policy question_steps_update_anon on public.question_steps
      for update to anon using (true) with check (true);
  end if;
end$$;

-- report_jobs: allow UPDATE in dev so report_worker can lock/update status without service role.
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='report_jobs' and policyname='report_jobs_update_anon'
  ) then
    create policy report_jobs_update_anon on public.report_jobs
      for update to anon using (true) with check (true);
  end if;
end$$;

