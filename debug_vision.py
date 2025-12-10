#!/usr/bin/env python3
"""调试 Vision 分析原始内容"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/Users/frank/Documents/网页软件开发/作业检查大师/homework_agent/.env")
os.environ.setdefault("PYTHONPATH", "/Users/frank/Documents/网页软件开发/作业检查大师")

from homework_agent.services.vision import VisionClient, VisionProvider
from homework_agent.models.schemas import ImageRef
from homework_agent.utils.supabase_client import get_storage_client


async def upload_image(img_path: str, min_side: int = 28):
    """上传图片到 Supabase 并返回 URL"""
    storage_client = get_storage_client()
    public_urls = storage_client.upload_files(img_path, prefix="debug/", min_side=min_side)
    if public_urls:
        return public_urls[0]
    return None

def debug_vision(image_url: str, provider_name: str):
    """调试单个图片的 Vision 分析"""
    print(f"\n{'=' * 70}")
    print(f"Vision 调试: {provider_name}")
    print(f"URL: {image_url}")
    print(f"{'=' * 70}")

    client = VisionClient()

    # 选择提供商
    provider = VisionProvider.QWEN3 if provider_name.lower() == "qwen3" else VisionProvider.DOUBAO

    try:
        result = client.analyze(
            images=[ImageRef(url=image_url)],
            prompt="请详细识别并提取这张图片中的所有数学题目、学生的解答过程和最终答案。请按题目顺序列出。",
            provider=provider
        )

        print(f"\n✅ Vision 分析成功!")
        print(f"\n📝 原始识别内容:")
        print(f"{'=' * 70}")
        print(result.text)
        print(f"{'=' * 70}")

        return result.text

    except Exception as e:
        print(f"\n❌ Vision 分析失败: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """主函数"""
    test_dir = "/Users/frank/Desktop/作业档案/数学/202511/1105"
    img_files = list(Path(test_dir).glob("*.jpg"))

    if not img_files:
        print(f"❌ 在 {test_dir} 中未找到图片文件")
        return

    print(f"🔍 找到 {len(img_files)} 张图片")
    print(f"📋 文件列表: {[f.name for f in img_files]}")
    print("=" * 70)

    # 处理每张图片
    for img_path in img_files:
        print(f"\n\n处理图片: {img_path.name}")
        print("=" * 70)

        # 上传图片
        img_url = await upload_image(str(img_path))
        if not img_url:
            print(f"❌ 上传失败: {img_path.name}")
            continue

        print(f"✅ 上传成功: {img_url}")

        # 测试 Qwen3
        print(f"\n🤖 测试 Qwen3")
        qwen3_text = debug_vision(img_url, "qwen3")

        # 等待 3 秒
        await asyncio.sleep(3)

        # 测试 Doubao
        print(f"\n🤖 测试 Doubao")
        doubao_text = debug_vision(img_url, "doubao")

        # 对比
        print(f"\n{'=' * 70}")
        print("📊 对比分析")
        print(f"{'=' * 70}")

        if qwen3_text and doubao_text:
            print(f"\nQwen3 文本长度: {len(qwen3_text)} 字符")
            print(f"Doubao 文本长度: {len(doubao_text)} 字符")

            # 简单对比
            if "Problem 3" in doubao_text and "Problem 3" not in qwen3_text:
                print(f"\n⚠️  关键发现:")
                print(f"   Doubao 识别到了 'Problem 3'")
                print(f"   Qwen3 没有识别到 'Problem 3'")
                print(f"   这解释了为什么 Doubao 能发现错误，Qwen3 不能")

        # 等待 5 秒
        print(f"\n\n休息 5 秒...")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
