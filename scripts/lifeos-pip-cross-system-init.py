#!/usr/bin/env python3
import importlib.util
from pathlib import Path
repo=Path("/home/joshan/lifeos-platform");p=repo/"scripts/lifeos-pip-p6-p10-core.py"
s=importlib.util.spec_from_file_location("pipcore",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
db=m.connect();m.service(db,"continuous_pipeline","RUNNING");db.close();print("PIP_CROSS_SYSTEM_STATE=READY")
