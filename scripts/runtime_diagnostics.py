from __future__ import annotations

import json
import os
import urllib.request


API = os.getenv("WATCHER_API", "http://127.0.0.1:8765/api")


with urllib.request.urlopen(f"{API}/diagnostics", timeout=10) as response:
    print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))

