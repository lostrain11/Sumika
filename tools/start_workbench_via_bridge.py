"""Start the managed DSH workbench through the bridge's CSRF-protected route.

The bridge requires a client token for writes; fetch /api/manage/session first,
then POST with the token header, mirroring what the shell does.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def call(path, method="GET", payload=None, token=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Sumika-Csrf"] = token
    request = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:400]


status, session = call("/api/manage/session")
print("session:", status, session)
if status != 200:
    sys.exit(1)
token = session["csrf"] if isinstance(session, dict) else None

status, body = call("/api/workbench/start", "POST", {}, token)
print("start:", status, json.dumps(body, ensure_ascii=False)[:600])
