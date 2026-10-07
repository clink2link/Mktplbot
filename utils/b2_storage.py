"""Backblaze B2 storage helpers for Pastele.

B2 is an optional secondary copy. Telegram file_id remains the canonical
fallback, so a B2 outage must never make an upload fail.
"""
import asyncio
import logging
import mimetypes
import os
import re
import base64
import hashlib
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from cryptography.fernet import Fernet, InvalidToken

from config import BOT_TOKEN, DATABASE_URL, B2_CREDENTIAL_KEY
from database import get_pool

logger = logging.getLogger(__name__)


_SECRET_PREFIX = "enc:v1:"


def _credential_fernet() -> Fernet:
    """Return the stable Fernet key used for B2 application-key secrets.

    Production should set B2_CREDENTIAL_KEY and keep it unchanged.
    The legacy BOT_TOKEN|DATABASE_URL derivation remains only for backward
    compatibility with existing installations.
    """
    raw = (B2_CREDENTIAL_KEY or f"{BOT_TOKEN}|{DATABASE_URL}").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_b2_secret(value: str) -> str:
    value = str(value or "")
    if value.startswith(_SECRET_PREFIX):
        return value
    token = _credential_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return _SECRET_PREFIX + token


def decrypt_b2_secret(value: str) -> str:
    value = str(value or "")
    if not value.startswith(_SECRET_PREFIX):
        # Backward compatibility for a legacy plaintext row. New writes are
        # always encrypted; init_db migrates legacy rows when possible.
        return value
    token = value[len(_SECRET_PREFIX):]
    try:
        return _credential_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        raise RuntimeError("B2 application key tidak dapat didekripsi")


def log_b2_credential_key_status() -> None:
    if not B2_CREDENTIAL_KEY:
        logger.warning(
            "B2_CREDENTIAL_KEY is not set; using the legacy derived key. "
            "Set a stable B2_CREDENTIAL_KEY for production."
        )


async def migrate_b2_credentials() -> int:
    """Encrypt any legacy plaintext B2 application keys in-place."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT account_id, application_key FROM b2_storage_accounts"
    )
    changed = 0
    for row in rows:
        value = str(row["application_key"] or "")
        if value.startswith(_SECRET_PREFIX):
            continue
        await pool.execute(
            "UPDATE b2_storage_accounts SET application_key=$1, updated_at=NOW() "
            "WHERE account_id=$2",
            encrypt_b2_secret(value), int(row["account_id"])
        )
        changed += 1
    if changed:
        logger.info("🔐 Encrypted %s legacy B2 credential(s)", changed)
    return changed


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
    result = []
    for row in rows:
        item = dict(row)
        item["application_key"] = decrypt_b2_secret(item["application_key"])
        result.append(item)
    return result


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
    if not row:
        return None
    item = dict(row)
    item["application_key"] = decrypt_b2_secret(item["application_key"])
    return item


async def get_upload_account() -> Optional[dict[str, Any]]:
    accounts = await get_b2_accounts()
    return accounts[0] if accounts else None


def _normalize_b2_region(region: str, endpoint: str = "") -> str:
    """Normalize a Backblaze region/hostname into a boto3 region."""
    value = str(region or "").strip().strip("/")
    host = str(endpoint or "").strip().rstrip("/")
    if "://" in host:
        host = host.split("://", 1)[1].split("/", 1)[0]
    else:
        host = host.split("/", 1)[0]

    for candidate in (value, host):
        c = candidate.strip()
        if "://" in c:
            c = c.split("://", 1)[1].split("/", 1)[0]
        m = re.search(r"(?:^|\.)s3\.(us-[a-z]+-\d+)\.backblazeb2\.com$", c, re.I)
        if m:
            return m.group(1).lower()
        m = re.search(r"(us-[a-z]+-\d+)", c, re.I)
        if m:
            return m.group(1).lower()
    return ""


def _normalize_b2_endpoint(endpoint: str, region: str) -> str:
    """Normalize malformed Backblaze S3 endpoints to the canonical endpoint."""
    ep = str(endpoint or "").strip().rstrip("/")
    if not region:
        return (ep if ep.startswith(("http://", "https://")) else ("https://" + ep if ep else ""))

    host = ep
    if "://" in host:
        host = host.split("://", 1)[1].split("/", 1)[0]
    else:
        host = host.split("/", 1)[0]

    # Backblaze's canonical S3 endpoint. Fix values such as
    # s3.s3.us-east-005.backblazeb2.com.backblazeb2.com.
    if "backblazeb2.com" in host.lower() or not ep:
        return f"https://s3.{region}.backblazeb2.com"

    return ep if ep.startswith(("http://", "https://")) else "https://" + ep


def _client(account: dict[str, Any]):
    """Create a Backblaze B2 S3 client with a valid Boto3 region."""
    raw_region = str(account.get("region") or "").strip()
    endpoint = str(account.get("endpoint") or "").strip().rstrip("/")
    region = _normalize_b2_region(raw_region, endpoint)
    endpoint = _normalize_b2_endpoint(endpoint, region)

    kwargs = {
        "service_name": "s3",
        "aws_access_key_id": str(account["key_id"]).strip(),
        "aws_secret_access_key": str(account["application_key"]).strip(),
        "region_name": region or None,
        "config": BotoConfig(
            signature_version="s3v4",
            connect_timeout=30,
            read_timeout=120,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
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
            bucket = str(account["bucket"]).strip()
            key = str(object_key).lstrip("/")
            # boto3 download_file() internally calls HeadObject. Some B2 keys
            # can be permitted to read objects without HeadObject permission,
            # so stream the object directly with GetObject.
            response = client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            try:
                with open(destination, "wb") as fh:
                    while True:
                        chunk = body.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            finally:
                body.close()

        await asyncio.to_thread(_download_sync)
        logger.info(
            "B2 DOWNLOAD OK | account=%s | bucket=%s | key=%s",
            account_id, account.get("bucket"), object_key,
        )
        return True
    except Exception as exc:
        logger.exception(
            "B2 DOWNLOAD FAILED | account=%s | bucket=%s | region=%s | endpoint=%s | key=%s | error=%s",
            account_id, account.get("bucket"), account.get("region"),
            account.get("endpoint"), object_key, str(exc)[:500],
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
