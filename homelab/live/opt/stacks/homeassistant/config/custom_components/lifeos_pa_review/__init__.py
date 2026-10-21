"""Authenticated, short-lived Paperless OCR preview for the PA task review."""
import json
import re
import time
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

PREVIEWS = Path("/config/lifeos-pa-state/task-previews")
TASK_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,119}")
DOCUMENT_ID_RE = re.compile(r"[1-9][0-9]{0,11}")
MAX_AGE_SECONDS = 3600


class LifeOSPATaskReviewPreviewView(HomeAssistantView):
    """Serve only fresh review previews to authenticated Home Assistant users."""

    url = "/api/lifeos_pa_review/{task_id}"
    name = "api:lifeos_pa_review"
    requires_auth = True

    async def get(self, request, task_id):
        if not TASK_ID_RE.fullmatch(task_id or ""):
            raise web.HTTPNotFound()
        path = PREVIEWS / (task_id + ".json")
        try:
            raw = await self.hass.async_add_executor_job(path.read_text, "utf-8")
            payload = json.loads(raw)
        except FileNotFoundError:
            raise web.HTTPNotFound()
        except (OSError, ValueError, TypeError):
            raise web.HTTPNotFound()
        if not isinstance(payload, dict):
            raise web.HTTPNotFound()
        try:
            stale = time.time() - int(payload.get("generated_at") or 0) > MAX_AGE_SECONDS
        except (TypeError, ValueError):
            stale = True
        if (payload.get("schema") != "lifeos_pa_task_previews_v1"
                or payload.get("task_id") != task_id or stale):
            await self.hass.async_add_executor_job(path.unlink, True)
            raise web.HTTPNotFound()
        documents = []
        for item in payload.get("documents", [])[:10]:
            if not isinstance(item, dict) or not DOCUMENT_ID_RE.fullmatch(str(item.get("document_id") or "")):
                continue
            documents.append({
                "document_id": str(item["document_id"]),
                "title": str(item.get("title") or "Paperless document")[:200],
                "ocr_text": str(item.get("ocr_text") or "")[:5000],
            })
        response = web.json_response({
            "schema": "lifeos_pa_task_previews_v1",
            "task_id": task_id,
            "documents": documents,
        })
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return response

    async def delete(self, request, task_id):
        if not TASK_ID_RE.fullmatch(task_id or ""):
            raise web.HTTPNotFound()
        path = PREVIEWS / (task_id + ".json")
        try:
            await self.hass.async_add_executor_job(path.unlink)
        except FileNotFoundError:
            pass
        response = web.json_response({"deleted": True})
        response.headers["Cache-Control"] = "no-store, private"
        return response


async def async_setup(hass, config):
    hass.http.register_view(LifeOSPATaskReviewPreviewView())
    return True
