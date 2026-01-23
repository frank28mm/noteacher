
-- =========================
-- 用户反馈 (Feedback / Hidden Chat)
-- 简单的工单/聊天系统：用户与管理员的对话记录
-- =========================
create table if not exists public.feedback_messages (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  sender text not null, -- 'user' | 'admin'
  content text,
  images jsonb default '[]'::jsonb,
  is_read boolean default false, -- 用于红点提醒 (admin 读用户的，或 user 读 admin 的)
  created_at timestamptz not null default now()
);

alter table public.feedback_messages enable row level security;

-- 开发期 Anon 策略
do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'feedback_messages' and policyname = 'feedback_messages_select_anon'
  ) then
    create policy feedback_messages_select_anon on public.feedback_messages
      for select
      to anon
      using (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'feedback_messages' and policyname = 'feedback_messages_insert_anon'
  ) then
    create policy feedback_messages_insert_anon on public.feedback_messages
      for insert
      to anon
      with check (true);
  end if;
end$$;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'feedback_messages' and policyname = 'feedback_messages_update_anon'
  ) then
    create policy feedback_messages_update_anon on public.feedback_messages
      for update
      to anon
      using (true)
      with check (true);
  end if;
end$$;

-- 索引：按用户查询对话记录
create index if not exists feedback_messages_user_created_idx 
  on public.feedback_messages (user_id, created_at asc);

-- 索引：管理员查询所有有未读消息的用户（或用户查询未读回复）
create index if not exists feedback_messages_unread_idx
  on public.feedback_messages (user_id, sender, is_read);
