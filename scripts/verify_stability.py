
import sys
import os
import logging
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from tenacity import RetryError

# Add project root to path
sys.path.append(os.getcwd())

from homework_agent.main import app
from homework_agent.services.llm import LLMClient
from homework_agent.services.vision import VisionClient, VisionProvider
from httpx import ReadTimeout
from openai import RateLimitError


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

client = TestClient(app)

class StabilityTest(unittest.TestCase):
    def test_01_api_guardrails(self):
        logger.info("=== TEST 1: API Guardrails (Input Safety) ===")
        
        # Case 1.1: Localhost Blocking
        logger.info("Testing Localhost URL Blocking...")
        resp = client.post(
            "/api/v1/grade",
            json={
                "subject": "math",
                "images": [{"url": "http://localhost:8000/hack.jpg"}]
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("must be public", resp.json()["detail"])
        logger.info("✅ Localhost blocked correctly (400).")

        # Case 1.2: Doubao Base64 Rejection
        logger.info("Testing Doubao Base64 Rejection...")
        resp = client.post(
            "/api/v1/grade",
            json={
                "subject": "math",
                "vision_provider": "doubao",
                "images": [{"base64": "data:image/png;base64,AAAA"}]
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Doubao provider only accepts URLs", resp.json()["detail"])
        logger.info("✅ Doubao Base64 rejected correctly (400).")

    def test_02_service_resilience(self):
        logger.info("\n=== TEST 2: Service Resilience (Retry Logic) ===")
        
        llm = LLMClient()
        
        # Mock the requests library or OpenAI client to simulate timeout
        # LLMClient.grade_math calls self._get_client(provider).chat.completions.create(...)
        
        logger.info("Mocking OpenAI client to fail twice then succeed...")
        
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content='{"summary": "retry success", "wrong_items": []}'))]
        
        mock_client = MagicMock()
        # Side effect: ReadTimeout, ReadTimeout, Success
        # Note: We use httpx.ReadTimeout because it's in the retry exception list and easier to instantiate
        mock_client.chat.completions.create.side_effect = [
            ReadTimeout("Mock Timeout 1", request=MagicMock()),
            ReadTimeout("Mock Timeout 2", request=MagicMock()),
            mock_completion
        ]
        
        with patch.object(LLMClient, '_get_client', return_value=mock_client):
            # We override settings to use 'silicon' provider logic
            result = llm.grade_math("fake content", provider="silicon")
            
            self.assertEqual(result.summary, "retry success")
            # Verify call count: 1 initial + 2 retries = 3 calls
            self.assertEqual(mock_client.chat.completions.create.call_count, 3)
            logger.info(f"✅ Retry logic verified! Called {mock_client.chat.completions.create.call_count} times on failures.")

    def test_03_e2e_smoke(self):
        logger.info("\n=== TEST 3: End-to-End Smoke Test ===")
        # Use a stable public image (Wikipedia Logo)
        TEST_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/80/Wikipedia-logo-v2.svg/200px-Wikipedia-logo-v2.svg.png"
        
        logger.info(f"Sending real request to /grade with image: {TEST_IMAGE}...")
        resp = client.post(
            "/api/v1/grade",
            json={
                "subject": "math",
                "images": [{"url": TEST_IMAGE}],
                "vision_provider": "qwen3" # Default
            }
        )
        
        if resp.status_code != 200:
            logger.error(f"❌ E2E Failed: {resp.status_code} - {resp.text}")
            self.fail(f"E2E Request failed with {resp.status_code}")
            
        data = resp.json()
        logger.info(f"✅ E2E Success! Response Summary: {data.get('summary')}")
        self.assertIn("wrong_items", data)
        self.assertEqual(data["subject"], "math")

    def test_04_rate_limit_fail_fast(self):
        logger.info("\n=== TEST 4: Rate Limit Fail Fast ===")
        llm = LLMClient()
        
        mock_client = MagicMock()
        # Side effect: RateLimitError immediately
        mock_client.chat.completions.create.side_effect = RateLimitError("Rate limit exceeded", response=MagicMock(), body=None)
        
        with patch.object(LLMClient, '_get_client', return_value=mock_client):
            logger.info("Triggering RateLimitError (expecting NO retries)...")
            try:
                llm.grade_math("content")
                self.fail("Should have raised RateLimitError or Exception")
            except Exception as e:
                logger.info(f"Caught expected exception: {type(e).__name__}")
            
            # Verify call count is exactly 1 (no retries)
            self.assertEqual(mock_client.chat.completions.create.call_count, 1)
            logger.info("✅ Verified: Called exactly 1 time (Fail Fast confirmed).")

    def test_05_doubao_e2e_smoke(self):
        logger.info("\n=== TEST 5: Doubao E2E Smoke Test ===")
        TEST_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/80/Wikipedia-logo-v2.svg/200px-Wikipedia-logo-v2.svg.png"
        
        logger.info(f"Sending real request to /grade (Doubao) with image: {TEST_IMAGE}...")
        try:
            resp = client.post(
                "/api/v1/grade",
                json={
                    "subject": "math",
                    "images": [{"url": TEST_IMAGE}],
                    "vision_provider": "doubao"
                }
            )
            
            if resp.status_code != 200:
                logger.error(f"❌ Doubao E2E Failed: {resp.status_code} - {resp.text}")
                # We do NOT fail here if allow_fail=True logic is desired, but user asked to TEST it.
                # If credentials are missing, it might 500 or 400.
                self.fail(f"Doubao E2E Request failed with {resp.status_code}")
                
            data = resp.json()
            logger.info(f"✅ Doubao E2E Success! Response Summary: {data.get('summary')}")
            self.assertIn("wrong_items", data)
            
        except Exception as e:
            logger.error(f"Doubao test exception: {e}")
            raise

if __name__ == "__main__":
    unittest.main()
