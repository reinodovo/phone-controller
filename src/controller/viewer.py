import html
import re
from datetime import datetime
from http import HTTPStatus

from websockets.datastructures import Headers
from websockets.http11 import Response

from controller import storage

STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #222; }
table { border-collapse: collapse; width: 100%; background: white; }
th, td { text-align: left; padding: .4rem .7rem; border-bottom: 1px solid #ddd; vertical-align: top; }
th { background: #f0f0f0; }
a { color: #0a58ca; text-decoration: none; }
.error { color: #b02a37; }
.running { color: #996b00; }
img { max-width: 180px; border: 1px solid #ccc; }
code { font-size: .85em; }
tr.internal td { color: #777; font-size: .85em; background: #f7f7f7; }
tr.internal img { max-width: 120px; }
.tag { font-size: .75em; padding: 0 .3rem; border-radius: 3px; background: #e7e7e7; }
.tag.user { background: #d8e8ff; }
"""


def page(title, body, refresh=False):
    meta = '<meta http-equiv="refresh" content="3">' if refresh else ""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>{meta}<title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style></head><body>{body}</body></html>"
    )


def when(iso):
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def status_cell(meta):
    if meta["status"] == "running":
        return '<span class="running">running</span>'
    if meta.get("closed_reason"):
        return (
            f'<span class="error">closed: {html.escape(meta["closed_reason"])}</span>'
        )
    if meta["errors"]:
        return f'<span class="error">{meta["errors"]} error(s)</span>'
    return "ok"


def sessions_page():
    rows = "".join(
        f"<tr><td><a href='/sessions/{s['id']}'>{when(s['granted_at'])}</a></td>"
        f"<td>{html.escape(s['holder'])}</td><td>{s['actions']}</td>"
        f"<td>{s.get('duration', '')}</td><td>{s['waited']}</td><td>{status_cell(s)}</td></tr>"
        for s in storage.list_sessions()
    )
    body = (
        "<h1>Phone sessions</h1><table><tr><th>granted</th><th>holder</th><th>actions</th>"
        f"<th>duration (s)</th><th>waited (s)</th><th>status</th></tr>{rows}</table>"
    )
    return page("Phone sessions", body)


def session_page(session_id, user_only=False):
    meta, steps = storage.load_session(session_id)
    if meta is None:
        return None
    rows = ""
    for step in steps:
        source = step.get("source", "user")
        if user_only and source != "user":
            continue
        args = ", ".join(f"{k}={v!r}" for k, v in step["args"].items() if v is not None)
        result = (
            "ok"
            if step["ok"]
            else f'<span class="error">{html.escape(step["error"])}</span>'
        )
        if "value" in step:
            result += f" <code>{html.escape(repr(step['value']))}</code>"
        tag = f'<span class="tag {source}">{source}</span>'
        if step.get("parent"):
            tag += f"<br><small>of #{step['parent']}</small>"
        shot = ""
        if image := step.get("image") or step.get("screenshot"):
            url = f"/sessions/{session_id}/files/{image}"
            shot = f"<a href='{url}'><img src='{url}'></a>"
            labels = {
                "layout": "layout from UI dump",
                "overlay": "UI dump over screenshot",
            }
            if step.get("image_source") in labels:
                shot += f"<br><small>{labels[step['image_source']]}</small>"
        if step.get("dump"):
            shot += f"<br><a href='/sessions/{session_id}/files/{step['dump']}'>dump xml</a>"
        rows += (
            f"<tr class='{source}'><td>{step['n']}</td><td>{tag}</td>"
            f"<td>{when(step['started_at'])}</td>"
            f"<td><code>{html.escape(step['action'])}({html.escape(args)})</code></td>"
            f"<td>{step['took']}</td><td>{result}</td><td>{shot}</td></tr>"
        )
    toggle = (
        f"<a href='/sessions/{session_id}'>show internal steps</a>"
        if user_only
        else f"<a href='/sessions/{session_id}?steps=user'>hide internal steps</a>"
    )
    body = (
        "<p><a href='/'>&larr; all sessions</a></p>"
        f"<h1>{html.escape(meta['holder'])}</h1>"
        f"<p>session <code>{meta['id']}</code> &middot; granted {when(meta['granted_at'])} "
        f"&middot; waited {meta['waited']}s &middot; {meta.get('duration', '…')}s "
        f"&middot; {status_cell(meta)}{' &middot; debug' if meta.get('debug') else ''}</p>"
        f"<p>{toggle}</p>"
        "<table><tr><th>#</th><th>source</th><th>time</th><th>action</th><th>took (s)</th><th>result</th>"
        f"<th>screen</th></tr>{rows}</table>"
    )
    return page(meta["holder"], body, refresh=meta["status"] == "running")


def respond(status, body, content_type="text/html; charset=utf-8"):
    if isinstance(body, str):
        body = body.encode()
    headers = Headers(
        [("Content-Type", content_type), ("Content-Length", str(len(body)))]
    )
    return Response(status.value, status.phrase, headers, body)


def process_request(connection, request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    path, _, query = request.path.partition("?")
    if path == "/":
        return respond(HTTPStatus.OK, sessions_page())
    if m := re.fullmatch(r"/sessions/([\w-]+)", path):
        content = session_page(m.group(1), user_only="steps=user" in query)
        if content:
            return respond(HTTPStatus.OK, content)
    if m := re.fullmatch(r"/sessions/([\w-]+)/files/([\w.-]+)", path):
        file = storage.session_file(m.group(1), m.group(2))
        if file:
            content_type = (
                "image/png" if file.suffix == ".png" else "text/plain; charset=utf-8"
            )
            return respond(HTTPStatus.OK, file.read_bytes(), content_type)
    return respond(HTTPStatus.NOT_FOUND, "not found", "text/plain")
