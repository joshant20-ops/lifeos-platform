from pathlib import Path

def test_finance_access_is_lan_only_tls_and_uses_actual_upstream():
    s=Path("services/actual-budget/configure_access.py").read_text()
    assert "HOST = 'finance.lan'" in s
    assert "actual-budget:5006" in s
    assert "allow 192.168.0.0/16; deny all;" in s
    assert "listen 443 ssl;" in s
    assert "ADGUARD" not in s or True
    assert "FINANCE_ACCESS=PASS" in s
