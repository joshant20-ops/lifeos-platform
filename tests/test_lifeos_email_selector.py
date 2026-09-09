import importlib.util
from pathlib import Path

PATH = Path('homelab/live/home/joshan/automation/lifeos_email_selector.py')
spec = importlib.util.spec_from_file_location('selector', PATH)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def test_newsletter_is_not_archived():
    r = selector.classify({'subject': 'Weekly newsletter', 'body': 'Unsubscribe here'}, allow_ai=False)
    assert r['archive'] == 'NO'
    assert r['delivery'] == 'NO'


def test_invoice_is_archived():
    r = selector.classify({'subject': 'Your invoice', 'body': 'Invoice attached', 'attachments': ['invoice.pdf']}, allow_ai=False)
    assert r['archive'] == 'YES'
    assert r['delivery'] == 'NO'


def test_delivery_is_tracked_but_not_archived():
    r = selector.classify({'subject': 'Your parcel has been dispatched', 'body': 'Tracking number: ZXCV123456'}, allow_ai=False)
    assert r['archive'] == 'NO'
    assert r['delivery'] == 'YES'
    assert r['delivery_details']['status'] == 'DISPATCHED'
    assert r['delivery_details']['tracking_reference'] == 'zxcv123456'


def test_invoice_and_delivery_can_both_apply():
    r = selector.classify({'subject': 'Invoice and shipping confirmation', 'body': 'Your invoice is attached. Your parcel has shipped.'}, allow_ai=False)
    assert r['archive'] == 'YES'
    assert r['delivery'] == 'YES'


def test_ambiguous_fails_to_review_without_ai():
    r = selector.classify({'subject': 'Important information', 'body': 'Please read.'}, allow_ai=False)
    assert r['archive'] == 'REVIEW'


def test_bad_ai_json_fails_closed():
    r = selector._normalise_ai('not-json')
    assert r['archive'] == 'REVIEW'


def test_low_confidence_ai_fails_closed():
    r = selector._normalise_ai('{"archive":"YES","delivery":"NO","confidence":0.4,"reason":"maybe"}')
    assert r['archive'] == 'REVIEW'
