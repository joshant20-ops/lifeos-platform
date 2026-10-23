"""Exercise actual review view methods without HA installing hidden attributes."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'homelab/live/opt/stacks/homeassistant/config/custom_components/lifeos_pa_review/__init__.py'


class ReviewViewTests(unittest.TestCase):
    def test_setup_passes_hass_and_both_views_read_through_its_executor(self):
        # The real HomeAssistantView base has no self.hass. This stub deliberately
        # supplies none, so the previous implicit dependency fails this contract.
        base = types.ModuleType('homeassistant.components.http')
        base.HomeAssistantView = type('HomeAssistantView', (), {})
        with patch.dict(sys.modules, {'homeassistant.components.http': base}):
            spec = importlib.util.spec_from_file_location('review_views_contract', COMPONENT)
            component = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(component)
        class Hass:
            def __init__(self):
                self.views = []
                self.calls = 0
                self.http = types.SimpleNamespace(register_view=self.views.append)
            async def async_add_executor_job(self, fn, *args):
                self.calls += 1
                return fn(*args)
        async def scenario():
            hass = Hass()
            self.assertTrue(await component.async_setup(hass, {}))
            self.assertEqual(len(hass.views), 2)
            self.assertTrue(all(view.hass is hass and view.requires_auth for view in hass.views))
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                component.PREVIEWS = root / 'ocr'
                component.EMAILOPS_PREVIEWS = root / 'emailops'
                for folder in (component.PREVIEWS, component.EMAILOPS_PREVIEWS):
                    folder.mkdir()
                common = {'task_id': 'synthetic-task', 'generated_at': int(time.time())}
                (component.PREVIEWS / 'synthetic-task.json').write_text(json.dumps({**common,
                    'schema': 'lifeos_pa_task_previews_v1', 'documents': [
                        {'document_id': '1', 'title': 'Synthetic', 'ocr_text': 'PRIVATE_SENTINEL'}]}))
                (component.EMAILOPS_PREVIEWS / 'synthetic-task.json').write_text(json.dumps({**common,
                    'schema': 'lifeos_emailops_shadow_task_v1', 'summary': 'Synthetic summary',
                    'proposals': [{'title': 'Synthetic suggestion', 'due_date': None}]}))
                for view in hass.views:
                    response = await view.get(None, 'synthetic-task')
                    self.assertEqual(response.status, 200)
                    self.assertIn('no-store', response.headers['Cache-Control'])
                    self.assertEqual(json.loads(response.body)['task_id'], 'synthetic-task')
                await hass.views[0].delete(None, 'synthetic-task')
                self.assertFalse((component.PREVIEWS / 'synthetic-task.json').exists())
                self.assertEqual(hass.calls, 3)
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
