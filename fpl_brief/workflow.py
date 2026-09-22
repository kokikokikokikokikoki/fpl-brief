"""Small local status record for refresh and research workflows."""

from datetime import datetime, timezone

from .storage import read_json, write_atomic


PATH = "data/workflow_status.json"


def update(name, value, path=PATH, now=None):
    status = read_json(path, default={"schema_version": 1})
    if not isinstance(status, dict):
        status = {"schema_version": 1}
    current = now or datetime.now(timezone.utc)
    status[name] = value
    status["updated_at_utc"] = current.isoformat()
    write_atomic(path, status)
    return status
