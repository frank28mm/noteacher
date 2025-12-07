
import sys
import os
import logging
# Add project root to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from homework_agent.services.vision import VisionClient
from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.utils.settings import get_settings

logging.basicConfig(level=logging.INFO)

def test_ark_vision():
    client = VisionClient()
    # Use Baidu logo URL (likely accessible from Ark's Beijing servers)
    # This bypasses strict Base64 validation issues and firewall timeouts
    image_url = "https://www.baidu.com/img/flexible/logo/pc/result.png"

    print("\n--- Testing Doubao Vision (Ark) ---")
    print(f"Model configured: {client.ark_model}")

    try:
        img = ImageRef(url=image_url)
        result = client.analyze(
            images=[img],
            prompt="What is this? Answer in one word.",
            provider=VisionProvider.DOUBAO
        )
        print("✅ Success!")
        print("Result Text:", result.text)
        print("Raw Response keys:", result.raw.keys())

    except Exception as e:
        print("❌ Failed:", e)

if __name__ == "__main__":
    test_ark_vision()
