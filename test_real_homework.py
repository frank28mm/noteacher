import asyncio
import sys
from pathlib import Path
from typing import List

from homework_agent import HomeworkAgent


def resolve_images(args: List[str]) -> List[str]:
    if args:
        return args
    # Default sample
    return ["homework_img/IMG_0699.JPG"]


async def main():
    images = resolve_images(sys.argv[1:])
    missing = [p for p in images if not Path(p).exists()]
    if missing:
        print(f"[warn] Missing files: {missing}")

    agent = HomeworkAgent()
    print(f"Testing agent with: {images}")
    print("=" * 60)

    await agent.check_homework(images)


if __name__ == "__main__":
    asyncio.run(main())
