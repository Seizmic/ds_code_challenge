"""S3 access: credentials, S3 Select streaming, and cached downloads."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterator

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

from src import config
from src.logging_setup import human_bytes

logger = logging.getLogger(__name__)


class CredentialsError(RuntimeError):
    """Raised when the challenge credentials cannot be obtained."""


class S3SelectUnavailableError(RuntimeError):
    """Raised when the S3 Select API rejects the request outright."""


def fetch_credentials(url: str = config.CREDENTIALS_URL) -> dict[str, str]:
    """Fetch the challenge-supplied AWS credentials.

    Deliberately does NOT fall back to an ambient AWS profile or ``AWS_*``
    environment variables. S3 Select has been closed to new AWS customers since
    July 2024 (docs/discrepancies.md B1), so silently picking up a personal
    profile would fail Section 1 with an authorisation error that looks like a
    bug in this code. Failing loudly here is far cheaper to diagnose.

    The credentials are held in memory only and never written to disk.
    """
    last_error: Exception | None = None

    for attempt in range(1, config.HTTP_MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            break
        except Exception as exc:  # noqa: BLE001 - retried and re-raised below
            last_error = exc
            if attempt < config.HTTP_MAX_RETRIES:
                delay = config.HTTP_BACKOFF_FACTOR ** attempt
                logger.warning(
                    "Credential fetch attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt, config.HTTP_MAX_RETRIES, exc, delay,
                )
                time.sleep(delay)
    else:
        raise CredentialsError(
            f"Could not fetch challenge credentials from {url} after "
            f"{config.HTTP_MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    try:
        section = payload["s3"]
        credentials = {
            "aws_access_key_id": section["access_key"],
            "aws_secret_access_key": section["secret_key"],
        }
    except (KeyError, TypeError) as exc:
        raise CredentialsError(
            "Credential payload did not have the expected shape "
            '{"s3": {"access_key": ..., "secret_key": ...}}. '
            "The challenge may have changed the format."
        ) from exc

    logger.info("Fetched challenge credentials (access key ending ...%s)",
                credentials["aws_access_key_id"][-4:])
    return credentials


def make_s3_client(credentials: dict[str, str] | None = None):
    """Build an S3 client bound to the challenge credentials."""
    credentials = credentials or fetch_credentials()
    return boto3.client(
        "s3",
        region_name=config.AWS_REGION,
        config=Config(
            region_name=config.AWS_REGION,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
        **credentials,
    )


def s3_select_json(
    client,
    key: str,
    expression: str,
    bucket: str = config.S3_BUCKET,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run an S3 Select query returning newline-delimited JSON records.

    Returns the parsed records and the S3-reported scan statistics.

    The framing here is the part that is easy to get wrong. ``Payload`` events
    are arbitrary byte chunks and do NOT align to record boundaries -- a single
    JSON record can straddle two events. Parsing each chunk independently
    corrupts exactly those records, and does so silently on a small fraction of
    the data, which is the worst kind of bug. So we buffer and split on the
    record delimiter, carrying any partial tail into the next chunk.
    """
    try:
        response = client.select_object_content(
            Bucket=bucket,
            Key=key,
            ExpressionType="SQL",
            Expression=expression,
            InputSerialization={"JSON": {"Type": "DOCUMENT"}},
            OutputSerialization={"JSON": {"RecordDelimiter": "\n"}},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"AccessDenied", "InvalidRequest", "UnsupportedApiCall"}:
            raise S3SelectUnavailableError(
                f"S3 Select was rejected ({code}). S3 Select has been closed to "
                "new AWS customers since July 2024, so this usually means the "
                "request was signed with credentials other than the ones the "
                "challenge supplies. Check that no AWS_* environment variables "
                "or ~/.aws/credentials profile is overriding them. "
                "See docs/discrepancies.md B1."
            ) from exc
        raise

    records: list[dict[str, Any]] = []
    stats: dict[str, int] = {}
    buffer = ""
    malformed = 0

    for event in response["Payload"]:
        if "Records" in event:
            buffer += event["Records"]["Payload"].decode("utf-8")
            # Everything up to the last delimiter is complete; the tail may not be.
            *complete, buffer = buffer.split("\n")
            for line in complete:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed += 1
        elif "Stats" in event:
            stats = dict(event["Stats"]["Details"])
        elif "End" in event:
            break

    # Flush any final record not followed by a delimiter.
    tail = buffer.strip()
    if tail:
        try:
            records.append(json.loads(tail))
        except json.JSONDecodeError:
            malformed += 1

    if malformed:
        # Not silently tolerated: if framing is wrong we want to know loudly.
        raise ValueError(
            f"{malformed} record(s) from S3 Select could not be parsed as JSON. "
            "This indicates a record-framing fault, not a data problem."
        )

    if stats:
        logger.info(
            "S3 Select: scanned %s, processed %s, returned %s (%d records)",
            human_bytes(stats.get("BytesScanned", 0)),
            human_bytes(stats.get("BytesProcessed", 0)),
            human_bytes(stats.get("BytesReturned", 0)),
            len(records),
        )

    return records, stats


def download_cached(
    client,
    key: str,
    destination: Path | None = None,
    bucket: str = config.S3_BUCKET,
) -> Path:
    """Download an object, reusing a cached copy when the ETag is unchanged.

    The challenge inputs have been static since 2021/2022, so caching turns a
    rerun into a no-op. The ETag is checked rather than assumed, so a genuine
    upstream change still invalidates the cache.
    """
    destination = destination or (config.RAW_DIR / key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    etag_path = destination.with_suffix(destination.suffix + ".etag")

    head = client.head_object(Bucket=bucket, Key=key)
    remote_etag = head["ETag"].strip('"')
    size = head["ContentLength"]

    if destination.exists() and etag_path.exists():
        if etag_path.read_text(encoding="utf-8").strip() == remote_etag:
            logger.info("Cache hit for %s (%s) -- skipping download",
                        key, human_bytes(destination.stat().st_size))
            return destination
        logger.info("Cache stale for %s (ETag changed) -- re-downloading", key)

    logger.info("Downloading %s (%s)...", key, human_bytes(size))
    client.download_file(bucket, key, str(destination))
    etag_path.write_text(remote_etag, encoding="utf-8")
    return destination


def iter_object_lines(client, key: str, bucket: str = config.S3_BUCKET) -> Iterator[str]:
    """Stream an object's body line by line without buffering it whole."""
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    remainder = ""
    for chunk in body.iter_chunks(chunk_size=1024 * 1024):
        remainder += chunk.decode("utf-8")
        *lines, remainder = remainder.split("\n")
        yield from lines
    if remainder:
        yield remainder
