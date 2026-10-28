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
EMAILOPS_PREVIEWS = Path("/config/lifeos-pa-state/emailops-shadow")


class LifeOSEmailOpsShadowView(HomeAssistantView):
    """Expose only the matched task's private shadow result, without actions."""

    url = "/api/lifeos_emailops_shadow/{task_id}"
    name = "api:lifeos_emailops_shadow"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request, task_id):
        if not TASK_ID_RE.fullmatch(task_id or ""):
            raise web.HTTPNotFound()
        try:
            raw = await self.hass.async_add_executor_job((EMAILOPS_PREVIEWS / (task_id + ".json")).read_text, "utf-8")
            payload = json.loads(raw)
            valid = (isinstance(payload, dict)
                     and payload.get("schema") == "lifeos_emailops_shadow_task_v1"
                     and payload.get("task_id") == task_id
                     and time.time() - int(payload.get("generated_at") or 0) < 7 * 86400)
        except (OSError, ValueError, TypeError):
            valid = False
        if not valid:
            raise web.HTTPNotFound()
        response = web.json_response({
            "schema": "lifeos_emailops_shadow_task_v1", "task_id": task_id, "mode": "shadow",
            "summary": str(payload.get("summary") or "")[:4000],
            "proposals": [
                {"title": str(p.get("title") or "")[:300], "due_date": p.get("due_date")}
                for p in payload.get("proposals", [])[:20] if isinstance(p, dict)
            ],
        })
        response.headers["Cache-Control"] = "no-store, private"
        return response


class LifeOSPATaskReviewPreviewView(HomeAssistantView):
    """Serve only fresh review previews to authenticated Home Assistant users."""

    url = "/api/lifeos_pa_review/{task_id}"
    name = "api:lifeos_pa_review"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

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



class LifeOSEmailOpsSamplesView(HomeAssistantView):
    """Private review of every sampled analysis, including unmatched sources."""
    url = "/api/lifeos_emailops_samples"
    name = "api:lifeos_emailops_samples"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        path = EMAILOPS_PREVIEWS / "samples.json"
        try:
            def read():
                if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("unsafe")
                return json.loads(path.read_text())
            payload = await self.hass.async_add_executor_job(read)
            age = time.time() - int(payload.get("generated_at") or 0)
            if (payload.get("schema") != "lifeos_emailops_comparison_v1"
                    or payload.get("mode") != "shadow" or not 0 <= age < 7 * 86400
                    or not isinstance(payload.get("results"), list) or len(payload["results"]) > 8):
                raise ValueError("invalid")
            samples = []
            for row in payload["results"]:
                ids = row.get("source_message_ids")
                if not isinstance(ids, list) or len(ids) != 1 or not re.fullmatch(r"<[^<>\s\x00-\x1f]{1,298}>", str(ids[0])):
                    raise ValueError("identity")
                samples.append({
                    "source_message_id": ids[0],
                    "matched": bool(row.get("matched_task_ids")),
                    "summary": str(row.get("summary") or "")[:4000],
                    "proposals": [{"title":str(item.get("title") or "")[:300], "due_date":item.get("due_date")}
                                  for item in row.get("proposals", [])[:20] if isinstance(item,dict)],
                    "lifecycle":"UNKNOWN",
                })
        except (OSError, ValueError, TypeError, KeyError):
            raise web.HTTPNotFound()
        response = web.json_response({"schema":"lifeos_emailops_samples_v1",
                                      "generated_at":payload["generated_at"], "samples":samples})
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return response

async def async_setup(hass, config):
    hass.http.register_view(LifeOSPATaskReviewPreviewView(hass))
    hass.http.register_view(LifeOSEmailOpsShadowView(hass))
    hass.http.register_view(LifeOSEmailOpsSamplesView(hass))
    return True
