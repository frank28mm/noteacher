"""
Aliyun SMS provider for phone verification.

Uses Dypnsapi (号码认证服务) SendSmsVerifyCode + CheckSmsVerifyCode APIs.
Aliyun handles code generation and verification internally.

Required env vars:
- ALIYUN_ACCESS_KEY_ID
- ALIYUN_ACCESS_KEY_SECRET
- ALIYUN_SMS_SIGN_NAME (e.g., "速通互联验证码" or your approved sign)
- ALIYUN_SMS_TEMPLATE_CODE (e.g., "100001" for the system template)
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)

# Aliyun Dypnsapi endpoint
ALIYUN_DYPNSAPI_ENDPOINT = "https://dypnsapi.aliyuncs.com"
ALIYUN_API_VERSION = "2017-05-25"


def _percent_encode(s: str) -> str:
    """Aliyun-style percent encoding (RFC 3986 with ~ not encoded)."""
    return urllib.parse.quote(s, safe="~")


def _sign_request(
    params: Dict[str, str],
    access_key_secret: str,
    http_method: str = "POST",
) -> str:
    """
    Generate Aliyun API signature (Signature Version 1.0, HMAC-SHA1).
    """
    # Sort parameters alphabetically
    sorted_params = sorted(params.items())

    # Build canonicalized query string
    canonicalized = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params
    )

    # Build string to sign
    string_to_sign = f"{http_method}&%2F&{_percent_encode(canonicalized)}"

    # Calculate HMAC-SHA1
    key = f"{access_key_secret}&".encode("utf-8")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()

    return base64.b64encode(signature).decode("utf-8")


def _build_common_params(
    access_key_id: str,
    action: str,
) -> Dict[str, str]:
    """Build common request parameters for Aliyun API."""
    return {
        "Format": "JSON",
        "Version": ALIYUN_API_VERSION,
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Action": action,
    }


async def send_sms_verify_code(
    phone_number: str,
    *,
    scheme_name: str = "默认方案",
    code_length: int = 6,
    valid_time: int = 300,
    return_verify_code: bool = True,
) -> tuple[bool, Optional[str], str]:
    """
    Send SMS verification code via Aliyun SendSmsVerifyCode API.

    Args:
        phone_number: E.164 format phone number (with or without +86 prefix)
        scheme_name: Scheme name (max 20 chars)
        code_length: Verification code length (4-8)
        valid_time: Code validity in seconds (default 300)
        return_verify_code: Whether to return the generated code

    Returns:
        Tuple of (success, verify_code, message)
        - success: True if SMS sent successfully
        - verify_code: The generated code (if return_verify_code=True)
        - message: Error message or "OK"
    """
    settings = get_settings()

    access_key_id = str(getattr(settings, "aliyun_access_key_id", "") or "").strip()
    access_key_secret = str(
        getattr(settings, "aliyun_access_key_secret", "") or ""
    ).strip()
    sign_name = str(getattr(settings, "aliyun_sms_sign_name", "") or "").strip()
    template_code = str(getattr(settings, "aliyun_sms_template_code", "") or "").strip()

    if not all([access_key_id, access_key_secret, sign_name, template_code]):
        logger.error("Aliyun SMS credentials not configured")
        return False, None, "sms_provider_not_configured"

    # Normalize phone number (remove +86 prefix if present)
    phone = phone_number.lstrip("+")
    if phone.startswith("86"):
        phone = phone[2:]

    # Build request parameters
    params = _build_common_params(access_key_id, "SendSmsVerifyCode")
    params.update(
        {
            "PhoneNumber": phone,
            "SignName": sign_name,
            "TemplateCode": template_code,
            # Use ##code## placeholder - Aliyun generates the code
            # min = ValidTime in minutes (for template with ${min} variable)
            "TemplateParam": json.dumps(
                {"code": "##code##", "min": str(valid_time // 60)},
                ensure_ascii=False,
            ),
            "CodeLength": str(code_length),
            "ValidTime": str(valid_time),
            "CodeType": "1",  # Numeric only
            "ReturnVerifyCode": "true" if return_verify_code else "false",
            "SchemeName": scheme_name[:20],
        }
    )

    # Sign the request
    signature = _sign_request(params, access_key_secret)
    params["Signature"] = signature

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                ALIYUN_DYPNSAPI_ENDPOINT,
                data=params,
            )

        result = response.json()
        logger.info(
            "Aliyun SendSmsVerifyCode response: code=%s, message=%s",
            result.get("Code"),
            result.get("Message"),
        )

        if result.get("Code") == "OK":
            model = result.get("Model", {})
            verify_code = (
                str(model.get("VerifyCode", "")) if return_verify_code else None
            )
            return True, verify_code, "OK"
        else:
            error_code = result.get("Code", "UNKNOWN_ERROR")
            error_msg = result.get("Message", "Unknown error")
            logger.error("Aliyun SMS send failed: %s - %s", error_code, error_msg)
            return False, None, error_code

    except Exception as e:
        logger.exception("Aliyun SMS request failed: %s", e)
        return False, None, str(e)


async def check_sms_verify_code(
    phone_number: str,
    verify_code: str,
    *,
    scheme_name: str = "默认方案",
) -> tuple[bool, str]:
    """
    Verify SMS code via Aliyun CheckSmsVerifyCode API.

    Args:
        phone_number: E.164 format phone number
        verify_code: The code to verify
        scheme_name: Must match the scheme used in send

    Returns:
        Tuple of (success, message)
        - success: True if code verified successfully (VerifyResult == "PASS")
        - message: "PASS", "UNKNOWN", or error message
    """
    settings = get_settings()

    access_key_id = str(getattr(settings, "aliyun_access_key_id", "") or "").strip()
    access_key_secret = str(
        getattr(settings, "aliyun_access_key_secret", "") or ""
    ).strip()

    if not all([access_key_id, access_key_secret]):
        logger.error("Aliyun credentials not configured")
        return False, "sms_provider_not_configured"

    # Normalize phone number
    phone = phone_number.lstrip("+")
    if phone.startswith("86"):
        phone = phone[2:]

    # Build request parameters
    params = _build_common_params(access_key_id, "CheckSmsVerifyCode")
    params.update(
        {
            "PhoneNumber": phone,
            "VerifyCode": verify_code.strip(),
            "SchemeName": scheme_name[:20],
        }
    )

    # Sign the request
    signature = _sign_request(params, access_key_secret)
    params["Signature"] = signature

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                ALIYUN_DYPNSAPI_ENDPOINT,
                data=params,
            )

        result = response.json()
        logger.info(
            "Aliyun CheckSmsVerifyCode response: code=%s, verify_result=%s",
            result.get("Code"),
            result.get("Model", {}).get("VerifyResult"),
        )

        if result.get("Code") == "OK":
            model = result.get("Model", {})
            verify_result = model.get("VerifyResult", "UNKNOWN")
            if verify_result == "PASS":
                return True, "PASS"
            else:
                return False, verify_result
        else:
            error_code = result.get("Code", "UNKNOWN_ERROR")
            logger.error("Aliyun SMS verify failed: %s", error_code)
            return False, error_code

    except Exception as e:
        logger.exception("Aliyun SMS verify request failed: %s", e)
        return False, str(e)
