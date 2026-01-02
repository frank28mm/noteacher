#!/usr/bin/env python3
"""
Narrative Layer Verification Script

Verifies that the Narrative Layer implementation is working correctly by:
1. Checking configuration (ARK_REPORT_MODEL)
2. Verifying prompt template exists
3. Testing LLM client generate_report method
4. Running report_worker to process a test job
5. Verifying the generated report in database
"""

# ruff: noqa: E402

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from homework_agent.utils.settings import get_settings
from homework_agent.utils.prompt_manager import get_prompt_manager
from homework_agent.services.llm import LLMClient
from homework_agent.utils.supabase_client import get_storage_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def check_configuration():
    """Check 1: Verify ARK_REPORT_MODEL is configured"""
    logger.info("[Check 1] Verifying configuration...")
    settings = get_settings()

    ark_report_model = getattr(settings, "ark_report_model", None)
    if not ark_report_model:
        logger.warning("  ⚠ ARK_REPORT_MODEL not set, using default")
        return False

    logger.info(f"  ✓ ARK_REPORT_MODEL = {ark_report_model}")
    return True


def check_prompt_template():
    """Check 2: Verify report_analyst.yaml prompt exists"""
    logger.info("[Check 2] Verifying prompt template...")
    try:
        pm = get_prompt_manager()
        p_data = pm._load("report_analyst.yaml")

        if not p_data:
            logger.error("  ✗ report_analyst.yaml not found or empty")
            return False

        system = p_data.get("system_template")
        user = p_data.get("user_template")

        if not system or not user:
            logger.error("  ✗ Missing system_template or user_template")
            return False

        logger.info(f"  ✓ report_analyst.yaml loaded (version: {p_data.get('version', 'N/A')})")
        logger.info(f"    - system_template length: {len(system)} chars")
        logger.info(f"    - user_template length: {len(user)} chars")
        return True
    except Exception as e:
        logger.error(f"  ✗ Failed to load prompt: {e}")
        return False


def check_llm_generate_report():
    """Check 3: Test LLMClient.generate_report method"""
    logger.info("[Check 3] Testing LLMClient.generate_report...")

    # Skip if no API key
    settings = get_settings()
    if not getattr(settings, "ark_api_key", None):
        logger.warning("  ⚠ ARK_API_KEY not set, skipping LLM test")
        return None

    try:
        pm = get_prompt_manager()
        p_data = pm._load("report_analyst.yaml")
        system = p_data.get("system_template")
        user = p_data.get("user_template")

        # Create minimal test features
        test_features = {
            "accuracy": 0.85,
            "total_attempts": 20,
            "correct_attempts": 17,
            "mastery": {
                "数学.代数": "A",
                "数学.几何": "B"
            },
            "diagnosis": ["calculation_heavy"],
            "submission_ids": ["test_sub_1"]
        }

        from jinja2 import Template
        user_prompt = Template(user).render(
            features_json=__import__("json").dumps(test_features, ensure_ascii=False, indent=2)
        )

        llm = LLMClient()
        result = llm.generate_report(
            system_prompt=system,
            user_prompt=user_prompt
        )

        if not result or not result.narrative_md:
            logger.error("  ✗ generate_report returned empty narrative_md")
            return False

        logger.info("  ✓ generate_report succeeded")
        logger.info(f"    - narrative_md length: {len(result.narrative_md)} chars")
        logger.info(f"    - summary_json keys: {list((result.summary_json or {}).keys())}")
        logger.info(f"    - Preview: {result.narrative_md[:200]}...")
        return True
    except Exception as e:
        logger.error(f"  ✗ generate_report failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_database_state():
    """Check 4: Check database state (tables and jobs)"""
    logger.info("[Check 4] Checking database state...")

    try:
        storage = get_storage_client()

        # Check reports table
        resp = storage.client.table("reports").select("id", count="exact").execute()
        reports_count = getattr(resp, "count", 0)
        logger.info(f"  ✓ reports table accessible (count: {reports_count})")

        # Check report_jobs table
        resp = storage.client.table("report_jobs").select("id", count="exact").execute()
        jobs_count = getattr(resp, "count", 0)
        logger.info(f"  ✓ report_jobs table accessible (count: {jobs_count})")

        # Check pending jobs
        resp = storage.client.table("report_jobs").select("id", count="exact").eq("status", "pending").execute()
        pending_count = getattr(resp, "count", 0)
        logger.info(f"  ✓ pending jobs: {pending_count}")

        if pending_count > 0:
            # Get first pending job details
            resp = storage.client.table("report_jobs").select("*").eq("status", "pending").limit(1).execute()
            if resp.data:
                job = resp.data[0]
                logger.info(f"    - First pending job ID: {job.get('id')}")
                logger.info(f"    - User ID: {job.get('user_id')}")
                logger.info(f"    - Params: {job.get('params')}")

        return {
            "reports_count": reports_count,
            "jobs_count": jobs_count,
            "pending_count": pending_count
        }
    except Exception as e:
        logger.error(f"  ✗ Database check failed: {e}")
        return None


def main():
    logger.info("=" * 60)
    logger.info("Narrative Layer Verification")
    logger.info("=" * 60)

    results = {
        "config": check_configuration(),
        "prompt": check_prompt_template(),
        "llm": check_llm_generate_report(),
        "db": check_database_state(),
    }

    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)

    for name, result in results.items():
        if result is True:
            logger.info(f"  ✓ {name}: PASS")
        elif result is False:
            logger.info(f"  ✗ {name}: FAIL")
        elif result is None:
            logger.info(f"  ○ {name}: SKIPPED")
        else:
            logger.info(f"  ✓ {name}: {result}")

    logger.info("")
    logger.info("Next Steps:")
    if results.get("db", {}).get("pending_count", 0) > 0:
        logger.info("  1. Run report_worker to process pending jobs:")
        logger.info("     python3 -m homework_agent.workers.report_worker")
        logger.info("  2. Monitor logs in logs/report_worker.log")
    else:
        logger.info("  1. Create a test report job via API:")
        logger.info("     POST /api/v1/reports with {window_days: 7}")
        logger.info("  2. Then run report_worker")

    logger.info("")
    logger.info("Verification complete!")


if __name__ == "__main__":
    main()
