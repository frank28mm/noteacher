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
