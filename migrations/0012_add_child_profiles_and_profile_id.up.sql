create extension if not exists "uuid-ossp";

create table if not exists public.child_profiles (
  profile_id text primary key default uuid_generate_v4()::text,
  user_id text not null,
  display_name text not null,
  avatar_url text,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, display_name)
);

create index if not exists idx_child_profiles_user_id on public.child_profiles (user_id);

-- Ensure at most one default profile per user.
create unique index if not exists idx_child_profiles_user_default_unique
  on public.child_profiles (user_id)
  where is_default = true;

-- Add profile_id to fact tables (nullable for backward compatibility; we'll backfill below).
alter table if exists public.submissions add column if not exists profile_id text;
alter table if exists public.qindex_slices add column if not exists profile_id text;
alter table if exists public.question_attempts add column if not exists profile_id text;
alter table if exists public.question_steps add column if not exists profile_id text;
alter table if exists public.mistake_exclusions add column if not exists profile_id text;
alter table if exists public.report_jobs add column if not exists profile_id text;
alter table if exists public.reports add column if not exists profile_id text;

create index if not exists submissions_user_profile_created_idx
  on public.submissions (user_id, profile_id, created_at desc);

create index if not exists qindex_slices_user_profile_submission_idx
  on public.qindex_slices (user_id, profile_id, submission_id);

create index if not exists question_attempts_user_profile_created_idx
  on public.question_attempts (user_id, profile_id, created_at desc);

create index if not exists question_steps_user_profile_created_idx
  on public.question_steps (user_id, profile_id, created_at desc);

create index if not exists mistake_exclusions_user_profile_submission_idx
  on public.mistake_exclusions (user_id, profile_id, submission_id);

create unique index if not exists mistake_exclusions_user_profile_submission_item_unique
  on public.mistake_exclusions (user_id, profile_id, submission_id, item_id);

create index if not exists report_jobs_user_profile_created_idx
  on public.report_jobs (user_id, profile_id, created_at desc);

create index if not exists reports_user_profile_created_idx
  on public.reports (user_id, profile_id, created_at desc);

-- Backfill: ensure every user_id has a default profile, based on existing durable data.
-- NOTE: Some environments may not have public.users/public.user_wallets yet; guard those sources.
do $$
begin
  if to_regclass('public.users') is not null then
    insert into public.child_profiles (user_id, display_name, is_default)
    select distinct u.user_id, '默认', true
    from public.users u
    where not exists (
      select 1 from public.child_profiles p where p.user_id = u.user_id
    );
  end if;
end $$;

insert into public.child_profiles (user_id, display_name, is_default)
select distinct s.user_id, '默认', true
from public.submissions s
where coalesce(s.user_id, '') <> ''
  and not exists (
    select 1 from public.child_profiles p where p.user_id = s.user_id
  );

do $$
begin
  if to_regclass('public.user_wallets') is not null then
    insert into public.child_profiles (user_id, display_name, is_default)
    select distinct w.user_id, '默认', true
    from public.user_wallets w
    where coalesce(w.user_id, '') <> ''
      and not exists (
        select 1 from public.child_profiles p where p.user_id = w.user_id
      );
  end if;
end $$;

-- Backfill profile_id in fact tables to the user's default profile.
update public.submissions s
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = s.user_id
  and p.is_default = true
  and s.profile_id is null;

update public.qindex_slices q
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = q.user_id
  and p.is_default = true
  and q.profile_id is null;

update public.question_attempts a
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = a.user_id
  and p.is_default = true
  and a.profile_id is null;

update public.question_steps st
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = st.user_id
  and p.is_default = true
  and st.profile_id is null;

update public.mistake_exclusions e
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = e.user_id
  and p.is_default = true
  and e.profile_id is null;

update public.report_jobs j
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = j.user_id
  and p.is_default = true
  and j.profile_id is null;

update public.reports r
set profile_id = p.profile_id
from public.child_profiles p
where p.user_id = r.user_id
  and p.is_default = true
  and r.profile_id is null;
