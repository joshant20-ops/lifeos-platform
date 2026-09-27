#!/usr/bin/env python3
from pathlib import Path
import sys

path=Path(sys.argv[1])
text=path.read_text()
url="/local/house-status/lifeos-house-status-v3.js"
if url in text:
    print("HOUSE_STATUS_EXTRA_MODULE=present")
    raise SystemExit(0)
anchor="frontend:\n  themes: !include_dir_merge_named themes\n"
if anchor not in text:
    raise SystemExit("frontend themes anchor missing")
if "extra_module_url:" in text:
    raise SystemExit("existing extra_module_url requires explicit merge")
text=text.replace(anchor,anchor+"  extra_module_url:\n    - "+url+"\n",1)
path.write_text(text)
print("HOUSE_STATUS_EXTRA_MODULE=installed")
