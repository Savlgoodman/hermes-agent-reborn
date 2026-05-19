"""Upload a tiny 123.txt file through the Hermes Business API.

Usage:
  python scripts/business_api_upload_smoke.py
"""

from __future__ import annotations

import argparse
import os
import sys
from io import BytesIO
from typing import Any

import requests


def _load_hermes_env() -> None:
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


def _request_json(method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> dict[str, Any]:
    resp = requests.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 60), **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed: HTTP {resp.status_code}\n{resp.text}")
    return resp.json()


def main() -> int:
    _load_hermes_env()

    parser = argparse.ArgumentParser(description="Upload 123.txt containing hello through Business API.")
    parser.add_argument("--base-url", default=os.getenv("BUSINESS_API_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--api-key", default=os.getenv("BUSINESS_API_KEY"))
    parser.add_argument("--target-path", default="", help="Workspace-relative upload directory. Empty means root.")
    parser.add_argument("--content", default="hello")
    parser.add_argument("--filename", default="123.txt")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing BUSINESS_API_KEY. Set it in ~/.hermes/.env or pass --api-key.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.api_key}"}

    try:
        health = _request_json("GET", f"{base_url}/health", headers=headers)
        print(f"Connected: {health}")

        data = {
            "overwrite": "true" if args.overwrite else "false",
        }
        if args.target_path:
            data["target_path"] = args.target_path

        files = {
            "file": (
                args.filename,
                BytesIO(args.content.encode("utf-8")),
                "text/plain",
            )
        }
        uploaded = _request_json("POST", f"{base_url}/api/files", headers=headers, data=data, files=files)
    except Exception as exc:
        print(f"Upload failed: {exc}", file=sys.stderr)
        return 1

    print("Uploaded:")
    print(f"  file_id: {uploaded.get('file_id')}")
    print(f"  filename: {uploaded.get('filename')}")
    print(f"  path: {uploaded.get('path')}")
    print(f"  size: {uploaded.get('size')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
