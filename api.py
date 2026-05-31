"""HTTP API routes for the Tesla UPS bridge service."""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from i18n import _, detect_language_from_header

router = APIRouter()

# Injected at registration time from bridge.py via register()
_ctx: Dict[str, Any] = {
    "state": {},
    "sse_queue": None,
}


def register(state: Dict[str, Any], sse_queue: asyncio.Queue) -> None:
    """Bind shared state and SSE queue from bridge.py."""
    _ctx["state"] = state
    _ctx["sse_queue"] = sse_queue


def get_status_display(status: str, lang: str) -> str:
    """Get translated status label."""
    if "LB" in status:
        return _("status.low_battery", lang)
    if "OB" in status:
        return _("status.on_battery", lang)
    if "OL" in status:
        return _("status.online", lang)
    return _("status.unknown", lang)


@router.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Return the latest UPS and battery provider state."""
    return _ctx["state"]


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, lang: str | None = None) -> str:
    """Render a simple status dashboard for browser access."""
    if lang is None:
        accept_language = request.headers.get("accept-language")
        lang = detect_language_from_header(accept_language)

    st = _ctx["state"]
    color = "green" if st["status"] == "OL" else "red"
    status_display = get_status_display(st["status"], lang)

    grid_key = (
        "grid.connected" if st["grid"] == "SystemGridConnected" else "grid.down"
    )
    grid_display = _(grid_key, lang)

    provider_rows = []
    for p in st.get("providers", []):
        p_color = "green" if p.get("grid_connected") else "red"
        p_status = "grid.connected" if p.get("grid_connected") else "grid.down"
        p_status_text = _(p_status, lang)
        p_name = p.get("name", "unknown")
        p_soe = p.get("soe", 0.0)
        provider_rows.append(
            f'<tr><td style="padding:8px;">{p_name}</td>'
            f'<td style="padding:8px; color:{p_color};">{p_status_text}</td>'
            f'<td style="padding:8px;">{p_soe:.1f}%</td></tr>'
        )

    providers_table = ""
    if provider_rows:
        providers_table = f"""
        <table style="margin:20px auto; border-collapse:collapse;">
            <tr style="background:#f0f0f0;">
                <th style="padding:8px;">{_("dashboard.provider", lang)}</th>
                <th style="padding:8px;">{_("dashboard.grid", lang)}</th>
                <th style="padding:8px;">{_("dashboard.battery", lang)}</th>
            </tr>
            {''.join(provider_rows)}
        </table>
        """

    return f"""
    <html>
        <head>
            <title>{_("dashboard.title", lang)}</title>
            <meta http-equiv="refresh" content="15">
        </head>
        <body style="font-family:sans-serif; text-align:center; padding-top:50px;">
            <h1>{_("dashboard.title", lang)}</h1>
            <div style="font-size:2em; color:{color}; font-weight:bold;">{status_display}</div>
            <p>{_("dashboard.grid", lang)}: {grid_display}</p>
            <p>{_("dashboard.battery", lang)}: {st['soe']:.1f}%</p>
            {providers_table}
            <p style="color:gray;">
                {_("dashboard.last_notification", lang)}: {st['last_notified']}
            </p>
            <p style="color:gray; font-size:0.8em;">{_("dashboard.refreshing", lang)}</p>
        </body>
    </html>
    """


async def _sse_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events from the queue."""
    initial_event = {"event": "connected", "data": dict(_ctx["state"])}
    yield f"data: {json.dumps(initial_event)}\n\n"

    while True:
        try:
            event = await asyncio.wait_for(_ctx["sse_queue"].get(), timeout=30.0)
            yield f"data: {json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            yield ":keepalive\n\n"


@router.get("/api/events")
async def events_endpoint() -> StreamingResponse:
    """SSE endpoint for real-time state updates."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
