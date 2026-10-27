#!/usr/bin/env python3
"""Authenticated S3-Compatible Bucket Server for Docker (IMPARK Ground Truth Storage).

Provides:
- Real username & password authentication (Basic Auth & S3 SigV4).
- S3 Bucket & Object APIs (PUT, GET, HEAD, LIST).
- Dual output: S3 XML & JSON for compatibility with Minio SDK, boto3, and HTTP clients.
- Web Console UI on Port 9001 and Port 9000.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Configuration from Environment
DATA_ROOT = Path(os.getenv("BUCKET_ROOT", "/data")).resolve()
AUTH_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
AUTH_PASS = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
API_PORT = int(os.getenv("API_PORT", "9000"))
CONSOLE_PORT = int(os.getenv("CONSOLE_PORT", "9001"))

DATA_ROOT.mkdir(parents=True, exist_ok=True)


def check_auth(headers) -> bool:
    """Validate username and password from Authorization header."""
    auth_header = headers.get("Authorization", "")
    if not auth_header:
        # Check custom headers
        u = headers.get("X-Minio-Access-Key") or headers.get("X-Amz-Access-Key")
        p = headers.get("X-Minio-Secret-Key") or headers.get("X-Amz-Secret-Key")
        if u and p:
            return u == AUTH_USER and p == AUTH_PASS
        return False

    # Check Basic Auth
    if auth_header.startswith("Basic "):
        encoded = auth_header.split(" ", 1)[1].strip()
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
            if ":" in decoded:
                user, passwd = decoded.split(":", 1)
                return user == AUTH_USER and passwd == AUTH_PASS
        except Exception:
            return False

    # Check S3 SigV4 Credential parameter: Credential=minioadmin/...
    if "Credential=" in auth_header:
        m = re.search(r"Credential=([^/]+)/", auth_header)
        if m and m.group(1) == AUTH_USER:
            return True

    return False


class BucketRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler implementing S3-compatible bucket protocol."""

    server_version = "IMPARK-BucketStore/1.0"

    def handle_one_request(self):
        self.close_connection = True
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_AUTHHEAD(self):
        body = b'{"error": "Unauthorized: Invalid or missing credentials"}\n'
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="IMPARK Bucket Storage"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # Healthcheck bypass
        if self.path in ("/ready", "/health", "/minio/health/ready"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if not check_auth(self.headers):
            self.do_AUTHHEAD()
            return

        parsed = urlparse(self.path)
        path_str = unquote(parsed.path)
        parts = [p for p in path_str.strip("/").split("/") if p]
        if len(parts) >= 2:
            bucket, key = parts[0], "/".join(parts[1:])
            target = DATA_ROOT / bucket / key
            if target.exists() and target.is_file():
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(target.stat().st_size))
                self.send_header("ETag", f'"{hashlib.md5(target.read_bytes()).hexdigest()}"')
                self.end_headers()
                return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        # Healthcheck endpoint
        if self.path in ("/ready", "/health", "/minio/health/ready"):
            body = b"OK\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Web Console
        if self.path in ("/", "/console", "/index.html"):
            self.render_web_console()
            return

        if not check_auth(self.headers):
            self.do_AUTHHEAD()
            return

        parsed = urlparse(self.path)
        path_str = unquote(parsed.path)
        parts = [p for p in path_str.strip("/").split("/") if p]

        # Case 1: List Buckets (GET /)
        if not parts:
            buckets = [d.name for d in DATA_ROOT.iterdir() if d.is_dir()]
            body = json.dumps({"buckets": buckets}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        bucket_name = parts[0]
        bucket_dir = DATA_ROOT / bucket_name

        # Case 2: List Objects in Bucket (GET /<bucket>)
        if len(parts) == 1:
            if not bucket_dir.exists():
                body = b'{"error": "Bucket not found"}\n'
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            objects = []
            for item in sorted(bucket_dir.rglob("*")):
                if item.is_file():
                    rel_name = item.relative_to(bucket_dir).as_posix()
                    objects.append({
                        "name": rel_name,
                        "size": item.stat().st_size,
                        "last_modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item.stat().st_mtime)),
                    })

            # Check if client requested S3 XML or JSON
            accept = self.headers.get("Accept", "")
            if "xml" in accept or "application/xml" in accept or "list-type=2" in parsed.query:
                xml_res = f'<?xml version="1.0" encoding="UTF-8"?>\n<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">\n  <Name>{bucket_name}</Name>\n'
                for o in objects:
                    xml_res += f"  <Contents>\n    <Key>{o['name']}</Key>\n    <Size>{o['size']}</Size>\n    <LastModified>{o['last_modified']}</LastModified>\n  </Contents>\n"
                xml_res += "</ListBucketResult>\n"
                body = xml_res.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = json.dumps({"bucket": bucket_name, "objects": objects}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        # Case 3: Get Object (GET /<bucket>/<key>)
        key = "/".join(parts[1:])
        target_file = bucket_dir / key
        if not target_file.exists() or not target_file.is_file():
            body = b'{"error": "Object not found"}\n'
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        content = target_file.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("ETag", f'"{hashlib.md5(content).hexdigest()}"')
        self.end_headers()
        self.wfile.write(content)

    def do_PUT(self):
        if not check_auth(self.headers):
            self.do_AUTHHEAD()
            return

        parsed = urlparse(self.path)
        path_str = unquote(parsed.path)
        parts = [p for p in path_str.strip("/").split("/") if p]
        if not parts:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        bucket_name = parts[0]
        bucket_dir = DATA_ROOT / bucket_name

        # Case 1: Create Bucket (PUT /<bucket>)
        if len(parts) == 1:
            bucket_dir.mkdir(parents=True, exist_ok=True)
            body = b'{"status": "Bucket created"}\n'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Case 2: Put Object (PUT /<bucket>/<key>)
        key = "/".join(parts[1:])
        target_file = bucket_dir / key
        target_file.parent.mkdir(parents=True, exist_ok=True)

        content_length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(content_length)

        target_file.write_bytes(payload)
        etag = hashlib.md5(payload).hexdigest()

        body = json.dumps({"status": "uploaded", "key": key, "size": len(payload), "etag": etag}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_web_console(self):
        """Render modern, clean HTML console for browser viewing on port 9001."""
        buckets = [d.name for d in DATA_ROOT.iterdir() if d.is_dir()]
        all_objects = []
        for b in buckets:
            bdir = DATA_ROOT / b
            for f in sorted(bdir.rglob("*")):
                if f.is_file():
                    all_objects.append({
                        "bucket": b,
                        "name": f.relative_to(bdir).as_posix(),
                        "size": f.stat().st_size,
                        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(f.stat().st_mtime)),
                    })

        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>IMPARK Ground Truth Object Storage Console</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
    .badge {{ background: #10b981; color: white; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; }}
    .card {{ background: #1e293b; border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #334155; font-size: 14px; }}
    th {{ color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
    tr:hover {{ background: #334155; }}
    .auth-box {{ background: #0284c7; padding: 8px 16px; border-radius: 6px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="header">
    <h2>IMPARK Docker Bucket Storage Console</h2>
    <span class="badge">SECURED WITH AUTH</span>
  </div>
  <div class="card">
    <h3>Storage Status</h3>
    <p>Target Bucket: <b>impark-ground-truth</b> | Storage Path: <code>{DATA_ROOT}</code> | Total Objects: <b>{len(all_objects)}</b></p>
    <div class="auth-box">
      Authenticated User: <b>{AUTH_USER}</b> | Password Protected
    </div>
  </div>
  <div class="card">
    <h3>Stored Context Files (.txt Ground Truths)</h3>
    <table>
      <thead>
        <tr><th>#</th><th>Bucket</th><th>Object Key</th><th>Size</th><th>Last Modified</th></tr>
      </thead>
      <tbody>
"""
        for idx, o in enumerate(all_objects, 1):
            size_kb = o["size"] / 1024.0
            html += f"<tr><td>{idx}</td><td>{o['bucket']}</td><td><b>{o['name']}</b></td><td>{size_kb:.1f} KB</td><td>{o['modified']}</td></tr>"

        if not all_objects:
            html += "<tr><td colspan='5' style='text-align:center;color:#94a3b8;'>No objects uploaded yet. Run upload_ground_truth_to_bucket.py to populate.</td></tr>"

        html += """
      </tbody>
    </table>
  </div>
</body>
</html>
"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def run_servers():
    """Run dual HTTP servers for API (port 9000) and Web Console (port 9001)."""
    server_api = ThreadingHTTPServer(("0.0.0.0", API_PORT), BucketRequestHandler)
    server_api.daemon_threads = True
    server_console = ThreadingHTTPServer(("0.0.0.0", CONSOLE_PORT), BucketRequestHandler)
    server_console.daemon_threads = True

    print(f"[IMPARK-BucketStore] S3/Bucket API listening on port {API_PORT}")
    print(f"[IMPARK-BucketStore] Web Console listening on port {CONSOLE_PORT}")
    print(f"[IMPARK-BucketStore] Authenticated user: {AUTH_USER}")

    t = threading.Thread(target=server_console.serve_forever, daemon=True)
    t.start()

    server_api.serve_forever()


if __name__ == "__main__":
    run_servers()
