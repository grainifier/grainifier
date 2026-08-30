#!/usr/bin/env python3
"""Upload a dataset archive to Zenodo (or the Zenodo sandbox) via the REST API.

    python tools/zenodo_upload.py dist/grainifier-frame-stats-2026.08.tar.gz \
        --metadata dist/grainifier-frame-stats-2026.08.zenodo.json [--sandbox] [--publish]
    python tools/zenodo_upload.py ... --new-version <existing record id>   # later versions
    python tools/zenodo_upload.py ... --deposition <draft id> --publish     # publish a reviewed draft

The token is read from $ZENODO_TOKEN or from ~/.config/zenodo/token (sandbox:
$ZENODO_SANDBOX_TOKEN or ~/.config/zenodo/sandbox-token). Create one at
https://zenodo.org/account/settings/applications/ with scopes deposit:write + deposit:actions.

Without --publish the deposition stays a draft you can inspect in the browser (the DOI is
already reserved and printed); publishing is irreversible.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _ssl_context() -> ssl.SSLContext | None:
    """python.org builds on macOS ship without a CA bundle; use certifi's when available."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


_CTX = _ssl_context()


def token_for(sandbox: bool) -> str:
    env = "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN"
    if os.environ.get(env):
        return os.environ[env].strip()
    f = Path.home() / ".config/zenodo" / ("sandbox-token" if sandbox else "token")
    if f.exists():
        return f.read_text().strip()
    sys.exit(f"no token: set {env} or write it to {f}")


def api(base: str, token: str, method: str, path: str, body=None, raw: bytes | None = None, content_type="application/json"):
    url = path if path.startswith("http") else base + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = Request(url, data=data, method=method, headers={"Authorization": f"Bearer {token}", "Content-Type": content_type})
    try:
        with urlopen(req, context=_CTX) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except HTTPError as e:
        sys.exit(f"{method} {url} -> HTTP {e.code}: {e.read().decode()[:2000]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", nargs="?", help="archive to upload (omit with --deposition to only update metadata / publish)")
    ap.add_argument("--metadata", required=True, help="JSON with title, description, creators, license, keywords, ... (from tools/make_dataset.py)")
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--new-version", metavar="RECORD_ID", help="create a new version of an existing published record")
    ap.add_argument("--deposition", metavar="DEPOSITION_ID", help="act on an existing draft (re-set metadata, optionally --publish) instead of creating and uploading")
    a = ap.parse_args()

    base = "https://sandbox.zenodo.org/api" if a.sandbox else "https://zenodo.org/api"
    tok = token_for(a.sandbox)
    meta = json.loads(Path(a.metadata).read_text())
    meta = {k: v for k, v in meta.items() if k in ("title", "upload_type", "description", "creators", "license", "access_right", "keywords", "related_identifiers", "version", "notes")}
    meta.setdefault("upload_type", "dataset")
    meta.setdefault("access_right", "open")

    if a.deposition:
        dep_id = int(a.deposition)
        api(base, tok, "PUT", f"/deposit/depositions/{dep_id}", body={"metadata": meta})
        dep = api(base, tok, "GET", f"/deposit/depositions/{dep_id}")
        if a.archive:  # replace the draft's files
            for f in dep.get("files", []):
                api(base, tok, "DELETE", f["links"]["self"])
                print(f"removed {f['filename']}")
            p = Path(a.archive)
            print(f"uploading {p.name} ({p.stat().st_size / 1e6:.0f} MB) ...", flush=True)
            api(base, tok, "PUT", f"{dep['links']['bucket']}/{p.name}", raw=p.read_bytes(), content_type="application/octet-stream")
            dep = api(base, tok, "GET", f"/deposit/depositions/{dep_id}")
        print(f"deposition {dep_id}: {dep['links']['html']}  files: {[(f['filename'], f['checksum']) for f in dep.get('files', [])]}")
        if a.publish:
            dep = api(base, tok, "POST", f"/deposit/depositions/{dep_id}/actions/publish")
            print(f"published: {dep['links']['record_html']}  DOI {dep['doi']}  concept DOI {dep.get('conceptdoi')}")
        return
    if a.new_version:
        dep = api(base, tok, "POST", f"/deposit/depositions/{a.new_version}/actions/newversion")
        dep = api(base, tok, "GET", dep["links"]["latest_draft"])
        for f in dep.get("files", []):  # drop the previous version's files
            api(base, tok, "DELETE", f["links"]["self"])
    else:
        dep = api(base, tok, "POST", "/deposit/depositions", body={})
    dep_id = dep["id"]
    print(f"deposition {dep_id}: {dep['links']['html']}")

    api(base, tok, "PUT", f"/deposit/depositions/{dep_id}", body={"metadata": meta})
    bucket = dep["links"]["bucket"]
    p = Path(a.archive)
    print(f"uploading {p.name} ({p.stat().st_size / 1e6:.0f} MB) ...", flush=True)
    api(base, tok, "PUT", f"{bucket}/{p.name}", raw=p.read_bytes(), content_type="application/octet-stream")
    dep = api(base, tok, "GET", f"/deposit/depositions/{dep_id}")
    doi = dep.get("metadata", {}).get("prereserve_doi", {}).get("doi") or dep.get("doi")
    print(f"uploaded; reserved DOI: {doi}")
    if a.publish:
        dep = api(base, tok, "POST", f"/deposit/depositions/{dep_id}/actions/publish")
        print(f"published: {dep['links']['record_html']}  DOI {dep['doi']}  concept DOI {dep.get('conceptdoi')}")
    else:
        print("draft left unpublished — review it in the browser, then re-run with --publish (or publish there)")


if __name__ == "__main__":
    main()
