"""Active policy and feed versions.

Each request pins the versions active when it starts. Without both, protected
operations are refused. A4 adds policy validation, import and activation here.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActiveVersions:
    policy_version: int | None
    feed_version: int | None

    @property
    def ready(self) -> bool:
        return self.policy_version is not None and self.feed_version is not None


def active_versions(conn: sqlite3.Connection) -> ActiveVersions:
    active = {
        row["kind"]: row["version"]
        for row in conn.execute("SELECT kind, version FROM active_config").fetchall()
    }
    return ActiveVersions(policy_version=active.get("policy"), feed_version=active.get("feed"))
