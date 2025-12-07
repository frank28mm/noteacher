
import asyncio
import json
import logging
import sys
import os
from datetime import datetime

# Add project root to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from homework_agent.api.routes import save_mistakes, resolve_context_items, normalize_context_ids, cache_store
from homework_agent.services.llm import LLMClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_context_injection():
    """
    Test that mistakes saved via save_mistakes can be retrieved and used by the Socratic Tutor.
    """
    print("Initializing components...")
    
    # 1. Setup Data
    session_id = "test_ctx_session_001"
    
    # Mock a WrongItem (Math)
    wrong_item = {
        "item_id": "math_err_123",
        "question": "Calculate 2+2", # Note: real WrongItem might not have 'question' explicitly if it's in the image, but let's assume standard structure
        "reason": "Student answered 5",
        "knowledge_tags": ["Math", "Arithmetic"],
        "math_steps": [
            {
                "index": 1,
                "verdict": "incorrect",
                "expected": "2+2=4",
                "observed": "2+2=5",
                "hint": "Count again."
            }
        ]
    }
    
    # 2. Simulate /grade: Save Mistakes
    print(f"Saving mistakes for session {session_id}...")
    save_mistakes(session_id, [wrong_item])
    
    # Verify it's in cache
    cached = cache_store.get(f"mistakes:{session_id}")
    if not cached:
        print("❌ Failed to save mistakes to cache.")
        return
    print(f"✅ Mistakes cached: {len(cached['wrong_items'])} items.")

    # 3. Simulate /chat: Resolve Content
    # Client sends context_item_ids=["math_err_123"]
    requested_ids = ["math_err_123"]
    print(f"Resolving context for ids: {requested_ids}...")
    
    normalized_ids = normalize_context_ids(requested_ids)
    # Simulate retrieving mistakes again (as routes.py would)
    mistakes = cached['wrong_items']
    
    selected, missing = resolve_context_items(normalized_ids, mistakes)
    
    if not selected:
        print(f"❌ Failed to resolve item. Missing: {missing}")
        return
    
    print(f"✅ Resolved item: {selected[0]['item_id']}")
    
    # 4. Inject into LLM
    print("\n--- Testing LLM Context Injection ---")
    client = LLMClient()
    # Ensure usage of valid model
    if client.silicon_model == "gpt-4o": # Should be fixed by settings but double check
         client.silicon_model = "Qwen/Qwen2.5-72B-Instruct" 

    question = "我这道题哪里错了？"
    
    # Construct context payload similar to routes.py
    wrong_item_context = {
        "requested_ids": requested_ids,
        "items": selected
    }
    
    try:
        result = client.socratic_tutor(
            question=question,
            wrong_item_context=wrong_item_context,
            session_id=session_id,
            interaction_count=0,
            provider="silicon"
        )
        print(f"Assistant Response:\n{result.messages[0]['content']}")
        
        # Simple heuristic check: does the response mention '5' or '4' or 'Arithmetic'?
        content = result.messages[0]['content']
        if "5" in content or "4" in content or "2+2" in content:
             print("\n✅ Verification SUCCESS: LLM referenced the specific error context.")
        else:
             print("\n⚠️ Verification WARNING: LLM response might be generic. Check content.")
             
    except Exception as e:
        print(f"❌ LLM Call Failed: {e}")

if __name__ == "__main__":
    test_context_injection()
