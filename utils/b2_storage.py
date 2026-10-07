"""Backblaze B2 storage helpers for Pastele.

B2 is an optional secondary copy. Telegram file_id remains the canonical
fallback, so a B2 outage must never make an upload fail.
"""
import asyncio
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Optional

import boto3

from database import get_pool

logger = logging.getLogger(__name__)


def _safe_name(value: str) -> str:
    value = str(value or "file").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value[:180] or "file"


async def get_b2_accounts() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT account_id, name, region, endpoint, bucket,
               key_id, application_key, is_enabled, is_target,
               created_at, updated_at
        FROM b2_storage_accounts
        WHERE is_enabled=TRUE
        ORDER BY is_target DESC, account_id ASC
        """
    )
    return [dict(r) for r in rows]


async def get_b2_account(account_id: int) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT account_id, name, region, endpoint, bucket,
               key_id, application_key, is_enabled, is_target
        FROM b2_storage_accounts
        WHERE account_id=$1 AND is_enabled=TRUE
        """,
        int(account_id),
    )
    return dict(row) if row else None


async def get_upload_account() -> Optional[dict[str, Any]]:
    accounts = await get_b2_accounts()
    return accounts[0] if accounts else None


def _client(account: dict[str, Any]):
    kwargs = {
        "service_name": "s3",
        "aws_access_key_id": account["key_id"],
        "aws_secret_access_key": account["application_key"],
        "region_name": account["region"],
    }
    endpoint = str(account.get("endpoint") or "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs)


def _upload_sync(account: dict[str, Any], local_path: str, object_key: str,
                 content_type: Optional[str], file_size: int) -> dict[str, Any]:
    client = _client(account)
    extra = {}
    if content_type:
        extra["ContentType"] = content_type
    with open(local_path, "rb") as fh:
        if extra:
            client.upload_fileobj(
                fh, account["bucket"], object_key, ExtraArgs=extra
            )
        else:
            client.upload_fileobj(
                fh, account["bucket"], object_key
            )
    return {
        "account_id": int(account["account_id"]),
        "bucket": account["bucket"],
        "object_key": object_key,
        "file_size": int(file_size or 0),
        "content_type": content_type or "application/octet-stream",
        "storage": "backblaze_b2",
    }


async def upload_file_to_b2(
    local_path: str,
    *,
    file_name: str = "file",
    content_type: Optional[str] = None,
    account_id: Optional[int] = None,
    object_prefix: str = "pastelebot",
) -> Optional[dict[str, Any]]:
    """Upload one local file to the configured B2 account.

    Returns None on any B2 failure. Callers must keep Telegram file_id.
    """
    try:
        account = (
            await get_b2_account(account_id)
            if account_id
            else await get_upload_account()
        )
        if not account:
            return None

        size = Path(local_path).stat().st_size
        safe = _safe_name(file_name)
        object_key = f"{object_prefix}/{os.urandom(12).hex()}_{safe}"
        ctype = content_type or mimetypes.guess_type(file_name)[0]

        result = await asyncio.to_thread(
            _upload_sync,
            account,
            local_path,
            object_key,
            ctype,
            size,
        )
        logger.info(
            "B2 UPLOAD OK | account=%s | key=%s | size=%s",
            result["account_id"], result["object_key"], result["file_size"],
        )
        return result
    except Exception:
        logger.exception("B2 UPLOAD FAILED; Telegram file_id remains fallback")
        return None


async def download_file_from_b2(
    account_id: int,
    object_key: str,
    destination: str,
) -> bool:
    """Download one B2 object to a local file.

    Used by the Showjs bridge. Failures are returned as False so the caller
    can show a controlled error instead of crashing the bot.
    """
    try:
        account = await get_b2_account(int(account_id))
        if not account:
            logger.error("B2 DOWNLOAD: account %s not configured", account_id)
            return False

        def _download_sync():
            client = _client(account)
            client.download_file(
                account["bucket"],
                str(object_key),
                destination,
            )

        await asyncio.to_thread(_download_sync)
        return True
    except Exception:
        logger.exception(
            "B2 DOWNLOAD FAILED | account=%s | key=%s",
            account_id,
            object_key,
        )
        return False


async def check_b2_account(account_id: int) -> dict[str, Any]:
    """Non-destructive B2 health check for the Admin panel."""
    try:
        account = await get_b2_account(int(account_id))
        if not account:
            return {"ok": False, "account_id": int(account_id), "error": "account_not_configured"}

        def _check():
            client = _client(account)
            client.head_bucket(Bucket=account["bucket"])
            return True

        await asyncio.to_thread(_check)
        return {
            "ok": True,
            "account_id": int(account_id),
            "bucket": account["bucket"],
            "region": account["region"],
        }
    except Exception as exc:
        logger.warning("B2 HEALTH FAILED | account=%s | %s", account_id, exc)
        return {
            "ok": False,
            "account_id": int(account_id),
            "error": str(exc)[:240],
        }
