from __future__ import annotations

import os
import shutil
from pathlib import Path


TEST_APP_DATA = Path.cwd() / "app-data" / "pytest"
os.environ.setdefault("LOCAL_SCRIBE_APP_DATA", str(TEST_APP_DATA))
os.environ.setdefault("LOCAL_SCRIBE_PROVIDER", "mock")
os.environ.setdefault("LOCAL_SCRIBE_OCR_PROVIDER", "mock")


def pytest_sessionstart() -> None:
    shutil.rmtree(TEST_APP_DATA, ignore_errors=True)


def pytest_sessionfinish() -> None:
    shutil.rmtree(TEST_APP_DATA, ignore_errors=True)
