-- Production RLS hardening (complete)
--
-- Purpose:
-- - Remove dev-time permissive anon policies ("using (true)")
-- - Ensure authenticated users can only access their own rows (user_id = auth.uid())
-- - Allow workers/service role to read/write when needed
--
-- Apply via Supabase Dashboard -> SQL Editor.
-- Safety: intended for production; review in a staging branch first.

-- Ensure RLS is enabled on target tables.
alter table if exists public.question_attempts enable row level security;
alter table if exists public.question_steps enable row level security;
alter table if exists public.report_jobs enable row level security;
alter table if exists public.feedback_messages enable row level security;

-- Server-owned tables (should not be exposed to anon/authenticated in production).
alter table if exists public.users enable row level security;
alter table if exists public.user_wallets enable row level security;
alter table if exists public.usage_ledger enable row level security;
alter table if exists public.bt_grants enable row level security;
alter table if exists public.child_profiles enable row level security;
alter table if exists public.redeem_cards enable row level security;
alter table if exists public.admin_audit_logs enable row level security;

-- ------------------------------------------------------------
-- feedback_messages
-- ------------------------------------------------------------
drop policy if exists feedback_messages_select_anon on public.feedback_messages;
drop policy if exists feedback_messages_insert_anon on public.feedback_messages;
drop policy if exists feedback_messages_update_anon on public.feedback_messages;

drop policy if exists feedback_messages_select_own on public.feedback_messages;
drop policy if exists feedback_messages_insert_own on public.feedback_messages;
drop policy if exists feedback_messages_update_own on public.feedback_messages;

create policy feedback_messages_select_own on public.feedback_messages
  for select to authenticated
  using (auth.uid()::text = user_id);

create policy feedback_messages_insert_own on public.feedback_messages
  for insert to authenticated
  with check (auth.uid()::text = user_id);

create policy feedback_messages_update_own on public.feedback_messages
  for update to authenticated
  using (auth.uid()::text = user_id);

-- ------------------------------------------------------------
-- question_attempts
-- ------------------------------------------------------------
drop policy if exists question_attempts_select_anon on public.question_attempts;
drop policy if exists question_attempts_insert_anon on public.question_attempts;
drop policy if exists question_attempts_update_anon on public.question_attempts;

drop policy if exists question_attempts_select_own on public.question_attempts;
drop policy if exists question_attempts_insert_own on public.question_attempts;
drop policy if exists question_attempts_update_own on public.question_attempts;

drop policy if exists question_attempts_select_service on public.question_attempts;
drop policy if exists question_attempts_insert_service on public.question_attempts;
drop policy if exists question_attempts_update_service on public.question_attempts;

create policy question_attempts_select_own on public.question_attempts
  for select to authenticated
  using (auth.uid()::text = user_id);

create policy question_attempts_insert_own on public.question_attempts
  for insert to authenticated
  with check (auth.uid()::text = user_id);

create policy question_attempts_update_own on public.question_attempts
  for update to authenticated
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Workers (service role)
create policy question_attempts_select_service on public.question_attempts
  for select to service_role
  using (true);

create policy question_attempts_insert_service on public.question_attempts
  for insert to service_role
  with check (true);

create policy question_attempts_update_service on public.question_attempts
  for update to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- question_steps
-- ------------------------------------------------------------
drop policy if exists question_steps_select_anon on public.question_steps;
drop policy if exists question_steps_insert_anon on public.question_steps;
drop policy if exists question_steps_update_anon on public.question_steps;

drop policy if exists question_steps_select_own on public.question_steps;
drop policy if exists question_steps_insert_own on public.question_steps;
drop policy if exists question_steps_update_own on public.question_steps;

drop policy if exists question_steps_select_service on public.question_steps;
drop policy if exists question_steps_insert_service on public.question_steps;
drop policy if exists question_steps_update_service on public.question_steps;

create policy question_steps_select_own on public.question_steps
  for select to authenticated
  using (auth.uid()::text = user_id);

create policy question_steps_insert_own on public.question_steps
  for insert to authenticated
  with check (auth.uid()::text = user_id);

create policy question_steps_update_own on public.question_steps
  for update to authenticated
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Workers (service role)
create policy question_steps_select_service on public.question_steps
  for select to service_role
  using (true);

create policy question_steps_insert_service on public.question_steps
  for insert to service_role
  with check (true);

create policy question_steps_update_service on public.question_steps
  for update to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- report_jobs
-- ------------------------------------------------------------
drop policy if exists report_jobs_update_anon on public.report_jobs;

drop policy if exists report_jobs_select_own on public.report_jobs;
drop policy if exists report_jobs_insert_own on public.report_jobs;
drop policy if exists report_jobs_update_own on public.report_jobs;

drop policy if exists report_jobs_select_service on public.report_jobs;
drop policy if exists report_jobs_insert_service on public.report_jobs;
drop policy if exists report_jobs_update_service on public.report_jobs;

create policy report_jobs_select_own on public.report_jobs
  for select to authenticated
  using (auth.uid()::text = user_id);

create policy report_jobs_insert_own on public.report_jobs
  for insert to authenticated
  with check (auth.uid()::text = user_id);

create policy report_jobs_update_own on public.report_jobs
  for update to authenticated
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Workers (service role)
create policy report_jobs_select_service on public.report_jobs
  for select to service_role
  using (true);

create policy report_jobs_insert_service on public.report_jobs
  for insert to service_role
  with check (true);

create policy report_jobs_update_service on public.report_jobs
  for update to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- server-only tables (service_role)
-- ------------------------------------------------------------

-- users
drop policy if exists users_select_anon on public.users;
drop policy if exists users_insert_anon on public.users;
drop policy if exists users_update_anon on public.users;
drop policy if exists users_delete_anon on public.users;

drop policy if exists users_select_own on public.users;
drop policy if exists users_insert_own on public.users;
drop policy if exists users_update_own on public.users;
drop policy if exists users_delete_own on public.users;

drop policy if exists users_select_service on public.users;
drop policy if exists users_insert_service on public.users;
drop policy if exists users_update_service on public.users;
drop policy if exists users_delete_service on public.users;

create policy users_select_service on public.users
  for select to service_role
  using (true);

create policy users_insert_service on public.users
  for insert to service_role
  with check (true);

create policy users_update_service on public.users
  for update to service_role
  using (true)
  with check (true);

create policy users_delete_service on public.users
  for delete to service_role
  using (true);

-- user_wallets
drop policy if exists user_wallets_select_anon on public.user_wallets;
drop policy if exists user_wallets_insert_anon on public.user_wallets;
drop policy if exists user_wallets_update_anon on public.user_wallets;
drop policy if exists user_wallets_delete_anon on public.user_wallets;

drop policy if exists user_wallets_select_own on public.user_wallets;
drop policy if exists user_wallets_insert_own on public.user_wallets;
drop policy if exists user_wallets_update_own on public.user_wallets;
drop policy if exists user_wallets_delete_own on public.user_wallets;

drop policy if exists user_wallets_select_service on public.user_wallets;
drop policy if exists user_wallets_insert_service on public.user_wallets;
drop policy if exists user_wallets_update_service on public.user_wallets;
drop policy if exists user_wallets_delete_service on public.user_wallets;

create policy user_wallets_select_service on public.user_wallets
  for select to service_role
  using (true);

create policy user_wallets_insert_service on public.user_wallets
  for insert to service_role
  with check (true);

create policy user_wallets_update_service on public.user_wallets
  for update to service_role
  using (true)
  with check (true);

create policy user_wallets_delete_service on public.user_wallets
  for delete to service_role
  using (true);

-- usage_ledger
drop policy if exists usage_ledger_select_anon on public.usage_ledger;
drop policy if exists usage_ledger_insert_anon on public.usage_ledger;
drop policy if exists usage_ledger_update_anon on public.usage_ledger;
drop policy if exists usage_ledger_delete_anon on public.usage_ledger;

drop policy if exists usage_ledger_select_own on public.usage_ledger;
drop policy if exists usage_ledger_insert_own on public.usage_ledger;
drop policy if exists usage_ledger_update_own on public.usage_ledger;
drop policy if exists usage_ledger_delete_own on public.usage_ledger;

drop policy if exists usage_ledger_select_service on public.usage_ledger;
drop policy if exists usage_ledger_insert_service on public.usage_ledger;
drop policy if exists usage_ledger_update_service on public.usage_ledger;
drop policy if exists usage_ledger_delete_service on public.usage_ledger;

create policy usage_ledger_select_service on public.usage_ledger
  for select to service_role
  using (true);

create policy usage_ledger_insert_service on public.usage_ledger
  for insert to service_role
  with check (true);

create policy usage_ledger_update_service on public.usage_ledger
  for update to service_role
  using (true)
  with check (true);

create policy usage_ledger_delete_service on public.usage_ledger
  for delete to service_role
  using (true);

-- bt_grants
drop policy if exists bt_grants_select_anon on public.bt_grants;
drop policy if exists bt_grants_insert_anon on public.bt_grants;
drop policy if exists bt_grants_update_anon on public.bt_grants;
drop policy if exists bt_grants_delete_anon on public.bt_grants;

drop policy if exists bt_grants_select_own on public.bt_grants;
drop policy if exists bt_grants_insert_own on public.bt_grants;
drop policy if exists bt_grants_update_own on public.bt_grants;
drop policy if exists bt_grants_delete_own on public.bt_grants;

drop policy if exists bt_grants_select_service on public.bt_grants;
drop policy if exists bt_grants_insert_service on public.bt_grants;
drop policy if exists bt_grants_update_service on public.bt_grants;
drop policy if exists bt_grants_delete_service on public.bt_grants;

create policy bt_grants_select_service on public.bt_grants
  for select to service_role
  using (true);

create policy bt_grants_insert_service on public.bt_grants
  for insert to service_role
  with check (true);

create policy bt_grants_update_service on public.bt_grants
  for update to service_role
  using (true)
  with check (true);

create policy bt_grants_delete_service on public.bt_grants
  for delete to service_role
  using (true);

-- child_profiles
drop policy if exists child_profiles_select_anon on public.child_profiles;
drop policy if exists child_profiles_insert_anon on public.child_profiles;
drop policy if exists child_profiles_update_anon on public.child_profiles;
drop policy if exists child_profiles_delete_anon on public.child_profiles;

drop policy if exists child_profiles_select_own on public.child_profiles;
drop policy if exists child_profiles_insert_own on public.child_profiles;
drop policy if exists child_profiles_update_own on public.child_profiles;
drop policy if exists child_profiles_delete_own on public.child_profiles;

drop policy if exists child_profiles_select_service on public.child_profiles;
drop policy if exists child_profiles_insert_service on public.child_profiles;
drop policy if exists child_profiles_update_service on public.child_profiles;
drop policy if exists child_profiles_delete_service on public.child_profiles;

create policy child_profiles_select_service on public.child_profiles
  for select to service_role
  using (true);

create policy child_profiles_insert_service on public.child_profiles
  for insert to service_role
  with check (true);

create policy child_profiles_update_service on public.child_profiles
  for update to service_role
  using (true)
  with check (true);

create policy child_profiles_delete_service on public.child_profiles
  for delete to service_role
  using (true);

-- redeem_cards
drop policy if exists redeem_cards_select_anon on public.redeem_cards;
drop policy if exists redeem_cards_insert_anon on public.redeem_cards;
drop policy if exists redeem_cards_update_anon on public.redeem_cards;
drop policy if exists redeem_cards_delete_anon on public.redeem_cards;

drop policy if exists redeem_cards_select_own on public.redeem_cards;
drop policy if exists redeem_cards_insert_own on public.redeem_cards;
drop policy if exists redeem_cards_update_own on public.redeem_cards;
drop policy if exists redeem_cards_delete_own on public.redeem_cards;

drop policy if exists redeem_cards_select_service on public.redeem_cards;
drop policy if exists redeem_cards_insert_service on public.redeem_cards;
drop policy if exists redeem_cards_update_service on public.redeem_cards;
drop policy if exists redeem_cards_delete_service on public.redeem_cards;

create policy redeem_cards_select_service on public.redeem_cards
  for select to service_role
  using (true);

create policy redeem_cards_insert_service on public.redeem_cards
  for insert to service_role
  with check (true);

create policy redeem_cards_update_service on public.redeem_cards
  for update to service_role
  using (true)
  with check (true);

create policy redeem_cards_delete_service on public.redeem_cards
  for delete to service_role
  using (true);

-- admin_audit_logs
drop policy if exists admin_audit_logs_select_anon on public.admin_audit_logs;
drop policy if exists admin_audit_logs_insert_anon on public.admin_audit_logs;
drop policy if exists admin_audit_logs_update_anon on public.admin_audit_logs;
drop policy if exists admin_audit_logs_delete_anon on public.admin_audit_logs;

drop policy if exists admin_audit_logs_select_own on public.admin_audit_logs;
drop policy if exists admin_audit_logs_insert_own on public.admin_audit_logs;
drop policy if exists admin_audit_logs_update_own on public.admin_audit_logs;
drop policy if exists admin_audit_logs_delete_own on public.admin_audit_logs;

drop policy if exists admin_audit_logs_select_service on public.admin_audit_logs;
drop policy if exists admin_audit_logs_insert_service on public.admin_audit_logs;
drop policy if exists admin_audit_logs_update_service on public.admin_audit_logs;
drop policy if exists admin_audit_logs_delete_service on public.admin_audit_logs;

create policy admin_audit_logs_select_service on public.admin_audit_logs
  for select to service_role
  using (true);

create policy admin_audit_logs_insert_service on public.admin_audit_logs
  for insert to service_role
  with check (true);

create policy admin_audit_logs_update_service on public.admin_audit_logs
  for update to service_role
  using (true)
  with check (true);

create policy admin_audit_logs_delete_service on public.admin_audit_logs
  for delete to service_role
  using (true);
