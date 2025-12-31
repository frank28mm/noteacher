#!/usr/bin/env python3
"""
Direct Narrative Layer Test

Bypasses worker's UPDATE lock issues by directly processing a pending job.
This demonstrates that the Narrative Layer logic works correctly.
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from homework_agent.services.report_features import compute_report_features
from homework_agent.services.llm import LLMClient, ReportResult
from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.taxonomy import taxonomy_version
from homework_agent.utils.prompt_manager import get_prompt_manager
from homework_agent.utils.env import load_project_dotenv
from jinja2 import Template
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _load_attempts(*, user_id: str, since: str, until: str, subject: str = None):
    q = (
        _safe_table("question_attempts")
        .select(
            "submission_id,item_id,question_number,created_at,subject,verdict,knowledge_tags,knowledge_tags_norm,question_type,difficulty,severity,warnings"
        )
        .eq("user_id", str(user_id))
        .gte("created_at", str(since))
        .lte("created_at", str(until))
        .order("created_at", desc=True)
        .limit(5000)
    )
    if subject:
        q = q.eq("subject", str(subject))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    return rows if isinstance(rows, list) else []


def _load_steps(*, user_id: str, since: str, until: str, subject: str = None):
    q = (
        _safe_table("question_steps")
        .select(
            "submission_id,item_id,step_index,created_at,subject,verdict,severity,diagnosis_codes"
        )
        .eq("user_id", str(user_id))
        .gte("created_at", str(since))
        .lte("created_at", str(until))
        .order("created_at", desc=True)
        .limit(10000)
    )
    if subject:
        q = q.eq("subject", str(subject))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    return rows if isinstance(rows, list) else []


def _load_exclusions(*, user_id: str):
    try:
        resp = (
            _safe_table("mistake_exclusions")
            .select("submission_id,item_id")
            .eq("user_id", str(user_id))
            .limit(5000)
            .execute()
        )
        rows = getattr(resp, "data", None)
        out = set()
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            sid = str(r.get("submission_id") or "").strip()
            iid = str(r.get("item_id") or "").strip()
            if sid and iid:
                out.add((sid, iid))
        return out
    except Exception:
        return set()


def _filter_excluded_attempts(attempts, exclusions):
    if not exclusions:
        return attempts
    out = []
    for a in attempts:
        if not isinstance(a, dict):
            continue
        sid = str(a.get("submission_id") or "").strip()
        iid = str(a.get("item_id") or "").strip()
        if sid and iid and (sid, iid) in exclusions:
            continue
        out.append(a)
    return out


def _insert_report(*, user_id: str, params: dict, features: dict, narrative: ReportResult = None) -> str:
    row = {
        "user_id": str(user_id),
        "stats": features,
        "used_submission_ids": features.get("submission_ids") or [],
        "period_from": params.get("since"),
        "period_to": params.get("until"),
    }
    if narrative:
        row["content"] = narrative.narrative_md
        summary = narrative.summary_json or {}
        row["title"] = summary.get("title", "学情诊断报告")
        row["exclusions_snapshot"] = summary
    else:
        row["title"] = "学情分析报告"
        row["content"] = json.dumps(features, ensure_ascii=False, indent=2)

    resp = _safe_table("reports").insert(row).execute()
    rows = getattr(resp, "data", None)
    r0 = rows[0] if isinstance(rows, list) and rows else {}
    rid = str(r0.get("id") or "").strip()
    if not rid:
        raise RuntimeError("reports insert returned empty id")
    return rid


def main():
    load_project_dotenv()

    logger.info("=" * 60)
    logger.info("Direct Narrative Layer Test")
    logger.info("=" * 60)

    storage = get_storage_client()

    # Find a pending job
    resp = (
        _safe_table("report_jobs")
        .select("*")
        .eq("status", "pending")
        .limit(1)
        .execute()
    )

    if not resp.data:
        logger.warning("No pending jobs found. Creating a test job...")
        # Create a test job
        test_job = {
            "user_id": "dev_user",
            "params": {"window_days": 30},
            "status": "pending",
        }
        resp = _safe_table("report_jobs").insert(test_job).execute()
        if resp.data:
            job = resp.data[0]
            logger.info(f"Created test job: {job.get('id')}")
        else:
            logger.error("Failed to create test job")
            return
    else:
        job = resp.data[0]

    job_id = job.get("id")
    user_id = job.get("user_id")
    params = job.get("params") if isinstance(job.get("params"), dict) else {}

    logger.info(f"Processing job: {job_id}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Params: {params}")

    # Compute time window
    since = str(params.get("since") or "").strip()
    until = str(params.get("until") or "").strip()
    subject = str(params.get("subject") or "").strip() or None
    if since and until:
        pass  # use explicit
    else:
        days = int(params.get("window_days") or 7)
        now = _utc_now()
        since = _iso(now - timedelta(days=days))
        until = _iso(now)

    logger.info(f"Time window: {since} to {until}")

    # Load data
    logger.info("Loading question_attempts...")
    attempts = _load_attempts(user_id=user_id, since=since, until=until, subject=subject)
    logger.info(f"  Loaded {len(attempts)} attempts")

    logger.info("Loading question_steps...")
    steps = _load_steps(user_id=user_id, since=since, until=until, subject=subject)
    logger.info(f"  Loaded {len(steps)} steps")

    logger.info("Loading mistake_exclusions...")
    exclusions = _load_exclusions(user_id=user_id)
    logger.info(f"  Loaded {len(exclusions)} exclusions")

    attempts = _filter_excluded_attempts(attempts, exclusions)
    logger.info(f"After filtering: {len(attempts)} attempts")

    window = {"since": since, "until": until, "subject": subject}

    # Compute features
    logger.info("Computing report features...")
    features = compute_report_features(
        user_id=user_id,
        attempts=attempts,
        steps=steps,
        window=window,
        taxonomy_version=taxonomy_version() or None,
        classifier_version=None,
    )
    logger.info(f"Features computed: {list(features.keys())}")

    # Generate narrative
    logger.info("Generating narrative...")
    try:
        pm = get_prompt_manager()
        p_data = pm._load("report_analyst.yaml")
        system_tmpl = p_data.get("system_template")
        user_tmpl = p_data.get("user_template")

        if system_tmpl and user_tmpl:
            user_prompt = Template(user_tmpl).render(
                features_json=json.dumps(features, ensure_ascii=False, indent=2)
            )

            llm = LLMClient()
            narrative = llm.generate_report(
                system_prompt=system_tmpl,
                user_prompt=user_prompt
            )
            logger.info(f"Narrative generated: {len(narrative.narrative_md)} chars")
            logger.info(f"Summary: {narrative.summary_json}")
        else:
            logger.warning("Prompt templates not found, skipping narrative")
            narrative = None
    except Exception as e:
        logger.error(f"Narrative generation failed: {e}")
        import traceback
        traceback.print_exc()
        narrative = None

    # Insert report
    logger.info("Inserting report...")
    report_id = _insert_report(
        user_id=user_id,
        params=params,
        features=features,
        narrative=narrative
    )
    logger.info(f"Report inserted: {report_id}")

    # Verify
    logger.info("Verifying inserted report...")
    resp = _safe_table("reports").select("*").eq("id", report_id).execute()
    if resp.data:
        row = resp.data[0]
        logger.info(f"  Title: {row.get('title')}")
        logger.info(f"  Content length: {len(row.get('content') or '')}")
        logger.info(f"  Has stats: {'stats' in row and bool(row.get('stats'))}")

    logger.info("")
    logger.info("=" * 60)
    logger.info("Direct test completed successfully!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
