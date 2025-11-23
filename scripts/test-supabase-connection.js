// 加载本地环境变量
import dotenv from 'dotenv';
// 先清空相关环境变量（ES 模块中 dotenv 的要求）
delete process.env.SUPABASE_URL;
delete process.env.SUPABASE_ANON_KEY;
// 重新配置
dotenv.config({ path: '.env.local' });
import { createClient } from '@supabase/supabase-js';

async function main() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;

  if (!url || !key) {
    console.error('请在 .env.local 中设置 SUPABASE_URL 与 SUPABASE_ANON_KEY');
    process.exit(1);
  }

  const supabase = createClient(url, key);

  // 通过对 REST 端点发起一个轻量 OPTIONS 请求来验证连通性
  try {
    const res = await fetch(`${url}/rest/v1/`, {
      method: 'OPTIONS',
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
      },
    });

    if (res.ok || res.status === 404) {
      console.log('Supabase 连接正常：', url);
    } else {
      console.error('连接响应异常：', res.status, res.statusText);
    }
  } catch (err) {
    console.error('无法连接到 Supabase：', err.message);
    process.exit(1);
  }

  // 尝试一次真实调用（使用不存在的表，期待返回错误但证明请求可达）
  try {
    const { error } = await supabase.from('__non_existing_table__').select('*').limit(1);
    if (error) {
      console.log('已与 Supabase API 建立通信（返回错误符合预期）：', error.message);
    } else {
      console.log('请求成功（如果你有公共表，可能返回数据）');
    }
  } catch (e) {
    console.error('调用 Supabase API 时异常：', e.message);
  }
}

main();
