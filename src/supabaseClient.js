import dotenv from 'dotenv';
// 先清空相关环境变量（ES 模块中 dotenv 的要求）
delete process.env.SUPABASE_URL;
delete process.env.SUPABASE_ANON_KEY;
// 重新配置
dotenv.config({ path: '.env.local' });
import { createClient } from '@supabase/supabase-js';

const { SUPABASE_URL, SUPABASE_ANON_KEY } = process.env;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  throw new Error('环境变量缺失：请在 .env.local 中设置 SUPABASE_URL 与 SUPABASE_ANON_KEY');
}

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
