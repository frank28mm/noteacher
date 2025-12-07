
import asyncio
import logging
import sys
import os
import json

# Add project root to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from homework_agent.services.llm import LLMClient
from homework_agent.models.schemas import SimilarityMode

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_grading_llm():
    """
    Test Math and English grading logic with simulated text input (mocking OCR results).
    Verifies that the LLM returns compliant JSON structured according to our Pydantic models.
    """
    print("Initializing LLM Client...")
    client = LLMClient()
    # Ensure usage of valid model for logic reasoning (Grading uses the reasoning model)
    if client.silicon_model == "gpt-4o":
         client.silicon_model = "Qwen/Qwen2.5-72B-Instruct" 
    
    print(f"Using model: {client.silicon_model}")

    # --- Test 1: Math Grading ---
    # Scenario: Linear equation, student error
    ocr_text_math = """
    题目: 解方程 2x + 5 = 15
    学生作答:
    Step 1: 2x = 15 + 5
    Step 2: 2x = 20
    Step 3: x = 10
    """
    
    print("\n--- Testing Math Grading (JSON Schema) ---")
    try:
        result_math = client.grade_math(
            text_content=ocr_text_math,
            provider="silicon"
        )
        print("✅ Math Grading Call Successful.")
        print(f"Summary: {result_math.summary}")
        print(f"Warnings: {result_math.warnings}")
        print(f"Wrong Items: {len(result_math.wrong_items)}")
        
        # Validation
        if result_math.wrong_items:
            item = result_math.wrong_items[0]
            print(f"First Error Reason: {item.get('reason')}")
            if "steps" in item or "math_steps" in item:
                 print("✅ Structure contains steps.")
            else:
                 print("⚠️ Warning: Structure missing explicit steps detail (might be okay if simple error).")
        else:
             print("⚠️ Warning: Expected errors but found none.")
             
    except Exception as e:
        print(f"❌ Math Grading Failed: {e}")
        import traceback
        traceback.print_exc()

    # --- Test 2: English Grading ---
    # Scenario: Translation, semantic matching
    ocr_text_english = """
    题目: Translate "I like playing football" into Chinese.
    标准答案: 我喜欢踢足球。
    学生作答: 我爱玩篮球。
    """
    
    print("\n--- Testing English Grading (JSON Schema) ---")
    try:
        result_eng = client.grade_english(
            text_content=ocr_text_english,
            mode=SimilarityMode.NORMAL,
            provider="silicon"
        )
        print("✅ English Grading Call Successful.")
        print(f"Summary: {result_eng.summary}")
        
        if result_eng.wrong_items:
             print(f"Verification: {result_eng.wrong_items[0].get('reason')}")
        else:
             print("⚠️ Warning: Expected error (football != basketball) but considered correct.")

    except Exception as e:
        print(f"❌ English Grading Failed: {e}")

if __name__ == "__main__":
    test_grading_llm()
