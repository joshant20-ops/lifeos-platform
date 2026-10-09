import importlib.util
import pathlib

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "lifeos-configure-ai-dns.py"
spec = importlib.util.spec_from_file_location("configure_ai_dns", MODULE_PATH)
configure_ai_dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_ai_dns)


def test_adds_adguard_rewrite_without_discarding_existing_dns_settings():
    source = """dns:
  bind_hosts:
    - 0.0.0.0
  rewrites: []
filters: []
"""
    result = configure_ai_dns.rewrite_config(source, "192.168.0.10")
    assert "  bind_hosts:\n    - 0.0.0.0" in result
    assert "  rewrites:\n    - domain: ai.lan\n      answer: 192.168.0.10" in result
    assert "filters: []" in result


def test_updates_existing_ai_rewrite_without_duplication():
    source = """dns:
  rewrites:
    - domain: printer.lan
      answer: 192.168.0.20
    - domain: ai.lan
      answer: 192.168.0.10
  upstream_dns:
    - 1.1.1.1
"""
    result = configure_ai_dns.rewrite_config(source, "192.168.0.30")
    assert result.count("domain: ai.lan") == 1
    assert "answer: 192.168.0.30" in result
    assert "domain: printer.lan" in result
    assert "  upstream_dns:\n    - 1.1.1.1" in result


def test_adds_rewrite_when_rewrites_key_is_absent():
    result = configure_ai_dns.rewrite_config("dns:\n  upstream_dns: []\n", "192.168.0.10")
    assert "  rewrites:\n    - domain: ai.lan\n      answer: 192.168.0.10" in result
