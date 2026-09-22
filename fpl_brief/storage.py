import json
import os
import tempfile
from pathlib import Path


def read_json(path, default=None):
    file = Path(path)
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else default


def write_atomic(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent)
    try:
        with handle:
            handle.write(content)
        os.replace(handle.name, target)
    except Exception:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
        raise
