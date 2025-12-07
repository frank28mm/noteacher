
import sys
import os
import logging
# Add project root to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from homework_agent.services.vision import VisionClient
from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.utils.settings import get_settings

logging.basicConfig(level=logging.INFO)

def test_qwen_vision():
    client = VisionClient()
    settings = get_settings()
    
    print("\n--- Testing Qwen3-VL Vision (SiliconFlow) ---")
    print(f"Model configured: {client.silicon_model}")
    
    # Use the Baidu logo URL for consistency and reliability
    image_url = "https://www.baidu.com/img/flexible/logo/pc/result.png"
    
    try:
        img = ImageRef(url=image_url)
        # Using a simple prompt to check recognition
        result = client.analyze(
            images=[img],
            prompt="Describe this image in detail.",
            provider=VisionProvider.QWEN3
        )
        print("✅ Success!")
        print("--- Response Content ---")
        print(result.text)
        print("------------------------")
        
        # Check for Thinking tags if present (handling DeepSeek/Qwen thinking styles)
        if "<think>" in result.text:
            print("ℹ️ Note: Output contains <think> tags.")
            
    except Exception as e:
        print("❌ Failed:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_qwen_vision()
