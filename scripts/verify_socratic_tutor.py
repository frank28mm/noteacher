
import asyncio
import json
import logging
import sys
import os

# Add src to python path to allow imports
# Add project root to python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from homework_agent.services.llm import LLMClient
from homework_agent.models.schemas import Subject, WrongItem

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_socratic_tutor():
    """
    Test the Socratic Tutor functionality with a real LLM call.
    """
    print("Initializing LLM Client...")
    try:
        # NOTE: Ensure env vars are set (SILICON_API_KEY / ARK_API_KEY)
        client = LLMClient()
    except Exception as e:
        print(f"Failed to initialize client: {e}")
        return

    # 1. Simulate a wrong item context (Math)
    # 题目：求解方程 2x + 5 = 15
    # 学生答案：x = 10 (错误，应该是 x = 5)
    # 错误原因：移项时未变号或者计算错误 (15-5=10, 10/2=5)。学生可能直接 15+5=20, 20/2=10? 或者 15-5=10 但是忘了除以2?
    # 让我们假设学生写了: 2x = 20, x = 10. (错误且常见)
    wrong_item = {
        "reason": "Calculated 2x = 20 instead of 2x = 10 (15 - 5)",
        "standard_answer": "x = 5",
        "knowledge_tags": ["Math", "Algebra", "Linear Equations"],
        "math_steps": [
            {
                "index": 1,
                "verdict": "correct",
                "expected": "2x = 15 - 5",
                "observed": "2x = 20", # This is actually incorrect execution of the step
                "hint": "Check the sign when moving +5 to the right side."
            }
        ]
    }
    
    # 2. Simulate User Question
    question = "这道题我哪里做错了？为什么不是 10？"
    
    print("\n--- Testing Round 1 (Interaction Count 0) ---")
    print(f"Question: {question}")
    
    try:
        result_0 = client.socratic_tutor(
            question=question,
            wrong_item_context=wrong_item,
            session_id="test_session_001",
            interaction_count=0
        )
        print(f"Assistant: {result_0.messages[0]['content']}")
        print(f"Status: {result_0.status}")
    except Exception as e:
        print(f"Round 1 Failed: {e}")

    # 3. Simulate User Follow-up (Round 2)
    # Suppose user says: "I did 15 plus 5."
    question_2 = "我是把 5 移过去加起来的啊，15+5=20。"
    
    print("\n--- Testing Round 2 (Interaction Count 1) ---")
    print(f"Question: {question_2}")
    
    try:
        result_1 = client.socratic_tutor(
            question=question_2,
            wrong_item_context=wrong_item,
            session_id="test_session_001",
            interaction_count=1  # Turn 2
        )
        print(f"Assistant: {result_1.messages[0]['content']}")
        print(f"Status: {result_1.status}")
    except Exception as e:
        print(f"Round 2 Failed: {e}")

if __name__ == "__main__":
    test_socratic_tutor()
