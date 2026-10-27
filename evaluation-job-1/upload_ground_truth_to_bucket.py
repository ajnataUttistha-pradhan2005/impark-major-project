#!/usr/bin/env python3
"""Upload Ground Truth Context Text Files to Docker Bucket Storage.

Strictly uploads .txt context files from ground truth directories,
ignoring any .json or non-txt files. Authenticates using username and password.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("impark.bucket_upload")


def upload_txt_ground_truths(
    endpoint: str = "localhost:9000",
    access_key: str = "minioadmin",
    secret_key: str = "minioadmin123",
    bucket_name: str = "impark-ground-truth",
    source_dir: Path | str = Path(__file__).resolve().parent / "neo4j ground truths",
    secure: bool = False,
) -> list[str]:
    """Upload only .txt ground truth files from source_dir to the bucket."""
    source_path = Path(source_dir).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Ground truth source directory not found: {source_path}")

    proto = "https" if secure else "http"
    base_url = f"{proto}://{endpoint}"
    auth_bytes = f"{access_key}:{secret_key}".encode("utf-8")
    auth_header = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"

    logger.info("Authenticating to Bucket Storage at %s as '%s'...", base_url, access_key)

    # 1. Ensure bucket exists (PUT /<bucket>)
    bucket_url = f"{base_url}/{bucket_name}"
    req = urllib.request.Request(bucket_url, method="PUT")
    req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Bucket '%s' ready (HTTP %d).", bucket_name, resp.status)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError(f"Authentication failed for user '{access_key}'. Check username/password.") from e
        logger.info("Bucket check returned HTTP %d (bucket ready).", e.code)
    except Exception as exc:
        raise ConnectionError(f"Could not connect to Bucket Storage at {base_url}: {exc}") from exc

    # 2. Collect strictly .txt files
    txt_files: list[tuple[Path, str]] = []
    skipped_count = 0

    for root, _, files in os.walk(source_path):
        for fname in files:
            file_path = Path(root) / fname
            if fname.lower().endswith(".txt"):
                obj_name = fname
                txt_files.append((file_path, obj_name))
            else:
                skipped_count += 1

    logger.info(
        "Discovered %d .txt ground-truth files to upload (strictly skipped %d non-txt files).",
        len(txt_files),
        skipped_count,
    )

    if not txt_files:
        raise ValueError(f"No .txt context files found in {source_path}")

    # 3. Upload each .txt file
    uploaded_objects: list[str] = []
    for fpath, obj_name in sorted(txt_files, key=lambda x: x[1]):
        file_bytes = fpath.read_bytes()
        file_size_kb = len(file_bytes) / 1024.0

        quoted_name = urllib.parse.quote(obj_name)
        obj_url = f"{base_url}/{bucket_name}/{quoted_name}"
        put_req = urllib.request.Request(obj_url, data=file_bytes, method="PUT")
        put_req.add_header("Authorization", auth_header)
        put_req.add_header("Content-Type", "text/plain; charset=utf-8")
        put_req.add_header("Content-Length", str(len(file_bytes)))

        with urllib.request.urlopen(put_req, timeout=15) as resp:
            if resp.status in (200, 201):
                logger.info("Uploaded %s (%.1f KB) -> %s/%s [OK]", fpath.name, file_size_kb, bucket_name, obj_name)
                uploaded_objects.append(obj_name)
            else:
                logger.warning("Upload of %s returned HTTP %d", fpath.name, resp.status)

    # 4. Verify bucket contents
    list_req = urllib.request.Request(f"{base_url}/{bucket_name}", method="GET")
    list_req.add_header("Authorization", auth_header)
    list_req.add_header("Accept", "application/json")

    with urllib.request.urlopen(list_req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        bucket_objects = data.get("objects", [])

    print("\n" + "=" * 70)
    print(f"DOCKER BUCKET UPLOAD SUMMARY: s3://{bucket_name}")
    print("=" * 70)
    for obj in sorted(bucket_objects, key=lambda o: o["name"]):
        size_kb = obj["size"] / 1024.0
        print(f"  [OK] {obj['name']:<45} ({size_kb:>7.1f} KB)")
    print("=" * 70)
    print(f"Total .txt files uploaded:   {len(uploaded_objects)}")
    print(f"Total non-txt files skipped: {skipped_count}")
    print(f"Bucket Web Console URL:      http://localhost:9001")
    print("=" * 70 + "\n")

    return uploaded_objects


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload strictly .txt ground truth context files to Docker Bucket with authentication."
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        help="Bucket server endpoint (default: localhost:9000)",
    )
    parser.add_argument(
        "--access-key",
        default=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        help="Bucket username / access key (default: minioadmin)",
    )
    parser.add_argument(
        "--secret-key",
        default=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        help="Bucket password / secret key (default: minioadmin123)",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("MINIO_BUCKET", "impark-ground-truth"),
        help="Bucket name (default: impark-ground-truth)",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "neo4j ground truths",
        help="Directory containing ground truth subfolders with .txt context files",
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        help="Use HTTPS connection if set",
    )

    args = parser.parse_args()

    try:
        upload_txt_ground_truths(
            endpoint=args.endpoint,
            access_key=args.access_key,
            secret_key=args.secret_key,
            bucket_name=args.bucket,
            source_dir=args.source_dir,
            secure=args.secure,
        )
    except Exception as exc:
        logger.error("Failed to upload ground truths to bucket: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
