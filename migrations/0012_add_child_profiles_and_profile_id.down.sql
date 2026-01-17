drop index if exists public.reports_user_profile_created_idx;
drop index if exists public.report_jobs_user_profile_created_idx;
drop index if exists public.mistake_exclusions_user_profile_submission_idx;
drop index if exists public.mistake_exclusions_user_profile_submission_item_unique;
drop index if exists public.question_steps_user_profile_created_idx;
drop index if exists public.question_attempts_user_profile_created_idx;
drop index if exists public.qindex_slices_user_profile_submission_idx;
drop index if exists public.submissions_user_profile_created_idx;

alter table if exists public.reports drop column if exists profile_id;
alter table if exists public.report_jobs drop column if exists profile_id;
alter table if exists public.mistake_exclusions drop column if exists profile_id;
alter table if exists public.question_steps drop column if exists profile_id;
alter table if exists public.question_attempts drop column if exists profile_id;
alter table if exists public.qindex_slices drop column if exists profile_id;
alter table if exists public.submissions drop column if exists profile_id;

drop index if exists public.idx_child_profiles_user_default_unique;
drop index if exists public.idx_child_profiles_user_id;
drop table if exists public.child_profiles;
