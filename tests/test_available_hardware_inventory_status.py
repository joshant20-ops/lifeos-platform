from pathlib import Path
import re

INVENTORY = Path(__file__).parents[1] / "docs" / "operations" / "available-hardware.md"


def test_hardware_inventory_rows_use_documented_statuses():
    text = INVENTORY.read_text()
    section = text.split("## Status definitions", 1)[1].split("## Inventory", 1)[0]
    documented = set(re.findall(r"^- \*\*(.+?)\*\* —", section, re.MULTILINE))
    assert "Reserved" in documented
    rows = [
        line for line in text.splitlines()
        if line.startswith("| ") and not line.startswith("| ---")
    ][1:]
    used = {line.split("|")[2].strip() for line in rows}
    assert used <= documented
