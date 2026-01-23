
-- 9. Feedback Messages (用户反馈)
drop policy if exists feedback_messages_select_anon on public.feedback_messages;
drop policy if exists feedback_messages_insert_anon on public.feedback_messages;
drop policy if exists feedback_messages_update_anon on public.feedback_messages;

create policy feedback_messages_select_own on public.feedback_messages
  for select to authenticated
  using (auth.uid()::text = user_id);

create policy feedback_messages_insert_own on public.feedback_messages
  for insert to authenticated
  with check (auth.uid()::text = user_id);

-- 更新策略：用户只能把自己的消息标记为已读（通常不需要 update content）
create policy feedback_messages_update_own on public.feedback_messages
  for update to authenticated
  using (auth.uid()::text = user_id);
