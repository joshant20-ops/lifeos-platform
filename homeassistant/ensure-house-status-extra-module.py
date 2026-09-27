#!/usr/bin/env python3
from pathlib import Path
import sys

path=Path(sys.argv[1])
text=path.read_text()
url="/local/house-status/lifeos-house-status-v4.js"
if url in text:
    print("HOUSE_STATUS_EXTRA_MODULE=present")
    raise SystemExit(0)
anchor="frontend:\n  themes: !include_dir_merge_named themes\n"
if anchor not in text:
    raise SystemExit("frontend themes anchor missing")
if "extra_module_url:" in text:
    import re
    updated=re.sub(r"(?m)^\s*- /local/house-status/lifeos-house-status(?:-card|-v[0-9]+)?\.js(?:\?[^\s]+)?\s*$", "    - "+url, text)
    if updated==text:
        raise SystemExit("existing extra_module_url requires explicit merge")
    path.write_text(updated)
    print("HOUSE_STATUS_EXTRA_MODULE=updated")
    raise SystemExit(0)
text=text.replace(anchor,anchor+"  extra_module_url:\n    - "+url+"\n",1)
path.write_text(text)
print("HOUSE_STATUS_EXTRA_MODULE=installed")
