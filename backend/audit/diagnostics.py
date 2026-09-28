"""Separate restricted diagnostics. Off by default and never in normal audit.

There is deliberately no public HTTP diagnostics route. A separately configured
operator capability is required even for local reads. Retention is enforced on
write and read; enabled stores should be placed on an encrypted private volume.
"""
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path


class RestrictedDiagnostics:
    def __init__(self, settings):
        self.enabled = settings.diagnostics_enabled
        self.retention = settings.diagnostics_retention_seconds
        self.key = settings.diagnostics_access_key
        self.path = Path(str(settings.database_path) + ".restricted.sqlite3")
        if self.enabled:
            if not self.key:
                raise ValueError("Enabled diagnostics require a separate diagnostics_access_key")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS traces (correlation_id TEXT, created REAL, payload TEXT)")
            os.chmod(self.path, 0o600)

    def write(self, correlation_id: str, payload: dict):
        if not self.enabled:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM traces WHERE created < ?", (time.time() - self.retention,))
            conn.execute("INSERT INTO traces VALUES (?, ?, ?)", (correlation_id, time.time(), json.dumps(payload)))

    def read(self, access_key: str) -> list[dict]:
        if not self.enabled or not self.key or not hmac.compare_digest(access_key, self.key):
            raise PermissionError("Restricted diagnostics access denied")
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM traces WHERE created < ?", (time.time() - self.retention,))
            return [{"correlationId": row[0], "payload": json.loads(row[1])}
                    for row in conn.execute("SELECT correlation_id, payload FROM traces")]
