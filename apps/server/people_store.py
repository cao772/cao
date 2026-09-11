from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

import platform_config

SUPPORTED_IDENTITY_PROVIDERS = {"local", "gitlab", "github", "agent", "manual"}
CURRENT_PROJECT_WINDOW_DAYS = 30


class PeopleConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _min_time(first: str | None, second: str | None) -> str | None:
    pairs = [(value, _parse_time(value)) for value in (first, second)]
    pairs = [(raw, parsed) for raw, parsed in pairs if parsed is not None]
    return min(pairs, key=lambda item: item[1])[0] if pairs else first or second


def _max_time(first: str | None, second: str | None) -> str | None:
    pairs = [(value, _parse_time(value)) for value in (first, second)]
    pairs = [(raw, parsed) for raw, parsed in pairs if parsed is not None]
    return max(pairs, key=lambda item: item[1])[0] if pairs else first or second


def _provider(value: str) -> str:
    provider = re.sub(r"\s+", "", str(value or "")).lower()
    if provider == "agent-user":
        provider = "agent"
    if provider not in SUPPORTED_IDENTITY_PROVIDERS:
        raise ValueError(f"unsupported identity provider: {provider}")
    return provider


def _external_id(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise ValueError("identity external_id is required")
    return text


def _person_id() -> str:
    return f"person-{uuid.uuid4().hex[:16]}"


def _identity_id() -> str:
    return f"identity-{uuid.uuid4().hex[:16]}"


def init_people_db() -> None:
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
                person_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS identities (
                identity_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                external_id TEXT COLLATE NOCASE NOT NULL,
                display_name TEXT,
                email TEXT,
                source TEXT,
                person_id TEXT,
                confirmed INTEGER NOT NULL DEFAULT 0,
                blocked_auto_link INTEGER NOT NULL DEFAULT 0,
                link_reason TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, external_id)
            );

            CREATE INDEX IF NOT EXISTS idx_identities_person
                ON identities(person_id);
            CREATE INDEX IF NOT EXISTS idx_identities_email
                ON identities(email);

            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                person_id TEXT,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unknown',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT,
                collector_version TEXT,
                projects_json TEXT NOT NULL DEFAULT '[]',
                workspace_count INTEGER NOT NULL DEFAULT 0,
                identity_conflict INTEGER NOT NULL DEFAULT 0,
                conflict_identity_refs_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_devices_person
                ON devices(person_id);

            CREATE TABLE IF NOT EXISTS person_projects (
                person_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                first_activity_at TEXT,
                last_activity_at TEXT,
                activity_sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(person_id, project_id)
            );

            CREATE INDEX IF NOT EXISTS idx_person_projects_project
                ON person_projects(project_id, last_activity_at DESC);
            """
        )


def _identity_row(conn: sqlite3.Connection, provider: str, external_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT identity_id, provider, external_id, display_name, email, source,
               person_id, confirmed, blocked_auto_link, link_reason,
               first_seen_at, last_seen_at, created_at, updated_at
        FROM identities
        WHERE provider=? AND external_id=? COLLATE NOCASE
        """,
        (provider, external_id),
    ).fetchone()


def _identity_by_id(conn: sqlite3.Connection, identity_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT identity_id, provider, external_id, display_name, email, source,
               person_id, confirmed, blocked_auto_link, link_reason,
               first_seen_at, last_seen_at, created_at, updated_at
        FROM identities WHERE identity_id=?
        """,
        (identity_id,),
    ).fetchone()


def _person_row(conn: sqlite3.Connection, person_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT person_id, display_name, status, created_at, updated_at FROM people WHERE person_id=?",
        (person_id,),
    ).fetchone()


def _create_person(
    conn: sqlite3.Connection,
    display_name: str,
    *,
    status: str = "active",
    person_id: str | None = None,
) -> str:
    display = re.sub(r"\s+", " ", str(display_name or "")).strip()
    if not display:
        raise ValueError("display_name is required")
    if status not in {"active", "inactive"}:
        raise ValueError("invalid person status")
    person_id = person_id or _person_id()
    now = _now()
    conn.execute(
        "INSERT INTO people(person_id, display_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (person_id, display, status, now, now),
    )
    return person_id


def create_person(display_name: str, *, status: str = "active") -> dict[str, Any]:
    init_people_db()
    with platform_config._db() as conn:
        person_id = _create_person(conn, display_name, status=status)
        row = _person_row(conn, person_id)
    return dict(row) if row else {}


def update_person(person_id: str, *, display_name: str, status: str) -> dict[str, Any]:
    init_people_db()
    display = re.sub(r"\s+", " ", str(display_name or "")).strip()
    if not display:
        raise ValueError("display_name is required")
    if status not in {"active", "inactive"}:
        raise ValueError("invalid person status")
    with platform_config._db() as conn:
        if _person_row(conn, person_id) is None:
            raise KeyError(person_id)
        conn.execute(
            "UPDATE people SET display_name=?, status=?, updated_at=? WHERE person_id=?",
            (display, status, _now(), person_id),
        )
        row = _person_row(conn, person_id)
    return dict(row) if row else {}


def _touch_identity(
    conn: sqlite3.Connection,
    *,
    provider: str,
    external_id: str,
    display_name: str | None = None,
    email: str | None = None,
    source: str | None = None,
    seen_at: str | None = None,
) -> sqlite3.Row:
    provider = _provider(provider)
    external_id = _external_id(external_id)
    display = re.sub(r"\s+", " ", str(display_name or "")).strip() or None
    normalized_email = re.sub(r"\s+", "", str(email or "")).strip().lower() or None
    seen_at = seen_at or _now()
    existing = _identity_row(conn, provider, external_id)
    now = _now()
    if existing is None:
        conn.execute(
            """
            INSERT INTO identities(
                identity_id, provider, external_id, display_name, email, source,
                person_id, confirmed, blocked_auto_link, link_reason,
                first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0, NULL, ?, ?, ?, ?)
            """,
            (
                _identity_id(),
                provider,
                external_id,
                display,
                normalized_email,
                source,
                seen_at,
                seen_at,
                now,
                now,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE identities
            SET display_name=COALESCE(?, display_name),
                email=COALESCE(?, email),
                source=COALESCE(?, source),
                first_seen_at=?,
                last_seen_at=?,
                updated_at=?
            WHERE identity_id=?
            """,
            (
                display,
                normalized_email,
                source,
                _min_time(existing["first_seen_at"], seen_at) or seen_at,
                _max_time(existing["last_seen_at"], seen_at) or seen_at,
                now,
                existing["identity_id"],
            ),
        )
    row = _identity_row(conn, provider, external_id)
    assert row is not None
    return row


def _assign_identity(
    conn: sqlite3.Connection,
    identity_id: str,
    person_id: str,
    *,
    confirmed: bool,
    reason: str,
) -> None:
    identity = _identity_by_id(conn, identity_id)
    if identity is None:
        raise KeyError(identity_id)
    if _person_row(conn, person_id) is None:
        raise KeyError(person_id)
    current = identity["person_id"]
    if current and current != person_id:
        raise PeopleConflict("identity already belongs to another person")
    conn.execute(
        """
        UPDATE identities
        SET person_id=?, confirmed=?, blocked_auto_link=0, link_reason=?, updated_at=?
        WHERE identity_id=?
        """,
        (person_id, 1 if confirmed else 0, reason, _now(), identity_id),
    )


def bind_identity(
    person_id: str,
    *,
    provider: str,
    external_id: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    init_people_db()
    provider = _provider(provider)
    external_id = _external_id(external_id)
    with platform_config._db() as conn:
        if _person_row(conn, person_id) is None:
            raise KeyError(person_id)
        identity = _touch_identity(
            conn,
            provider=provider,
            external_id=external_id,
            display_name=display_name,
            source="manual-binding",
        )
        _assign_identity(conn, identity["identity_id"], person_id, confirmed=True, reason="manual")
        row = _identity_by_id(conn, identity["identity_id"])
    refresh_identity_projection()
    return _public_identity(dict(row)) if row else {}


def unbind_identity(person_id: str, identity_id: str) -> dict[str, Any]:
    init_people_db()
    with platform_config._db() as conn:
        identity = _identity_by_id(conn, identity_id)
        if identity is None:
            raise KeyError(identity_id)
        if identity["person_id"] != person_id:
            raise PeopleConflict("identity does not belong to this person")
        conn.execute(
            """
            UPDATE identities
            SET person_id=NULL, confirmed=0, blocked_auto_link=1,
                link_reason='manual-unbound', updated_at=?
            WHERE identity_id=?
            """,
            (_now(), identity_id),
        )
        row = _identity_by_id(conn, identity_id)
    refresh_identity_projection()
    return _public_identity(dict(row)) if row else {}


def _find_email_person(conn: sqlite3.Connection, email: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", str(email or "")).strip().lower()
    if not normalized:
        return None
    rows = conn.execute(
        """
        SELECT DISTINCT person_id FROM identities
        WHERE lower(email)=? AND person_id IS NOT NULL
        """,
        (normalized,),
    ).fetchall()
    person_ids = {str(row["person_id"]) for row in rows if row["person_id"]}
    return next(iter(person_ids)) if len(person_ids) == 1 else None


def _ensure_local_or_agent_person(
    conn: sqlite3.Connection,
    identity: sqlite3.Row,
    *,
    counterpart_provider: str,
) -> str | None:
    if identity["person_id"]:
        return str(identity["person_id"])
    if identity["blocked_auto_link"]:
        return None
    counterpart = _identity_row(conn, counterpart_provider, str(identity["external_id"]))
    if counterpart and counterpart["person_id"]:
        _assign_identity(
            conn,
            str(identity["identity_id"]),
            str(counterpart["person_id"]),
            confirmed=False,
            reason="stable-local-agent-id",
        )
        return str(counterpart["person_id"])
    person_id = _create_person(conn, str(identity["display_name"] or identity["external_id"]))
    _assign_identity(
        conn,
        str(identity["identity_id"]),
        person_id,
        confirmed=False,
        reason=f"{identity['provider']}-observed",
    )
    return person_id


def _remote_actor(data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    author = data.get("author")
    username = data.get("author_username")
    display_name = data.get("author_name")
    email = data.get("author_email")
    if isinstance(author, dict):
        username = username or author.get("username") or author.get("login")
        display_name = display_name or author.get("name") or username
        email = email or author.get("email")
    elif isinstance(author, str):
        username = username or author
        display_name = display_name or author
    external_id = username or display_name
    external_text = re.sub(r"\s+", " ", str(external_id or "")).strip() or None
    display_text = re.sub(r"\s+", " ", str(display_name or external_text or "")).strip() or None
    email_text = re.sub(r"\s+", "", str(email or "")).strip().lower() or None
    return external_text, display_text, email_text


def _read_rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []


def _status(last_seen_at: str | None) -> str:
    parsed = _parse_time(last_seen_at)
    if parsed is None:
        return "unknown"
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age <= 30 * 60:
        return "online"
    if age <= 24 * 3600:
        return "stale"
    return "offline"


def _participation_state(last_activity_at: str | None) -> str:
    parsed = _parse_time(last_activity_at)
    if parsed is None:
        return "historical"
    return (
        "current"
        if datetime.now(timezone.utc) - parsed <= timedelta(days=CURRENT_PROJECT_WINDOW_DAYS)
        else "historical"
    )


def refresh_identity_projection() -> None:
    init_people_db()
    with platform_config._db() as conn:
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM person_projects")

        project_names: dict[str, str] = {}
        for row in _read_rows(conn, "SELECT project_id, project_name FROM projects"):
            project_names[str(row["project_id"])] = str(row["project_name"] or row["project_id"])

        activities: dict[tuple[str, str], dict[str, Any]] = {}
        device_observations: dict[str, list[dict[str, Any]]] = defaultdict(list)

        def note_activity(
            person_id: str | None,
            project_id: str | None,
            project_name: str | None,
            seen_at: str | None,
            source: str,
        ) -> None:
            if not person_id or not project_id:
                return
            key = (person_id, project_id)
            item = activities.setdefault(
                key,
                {
                    "person_id": person_id,
                    "project_id": project_id,
                    "project_name": project_name or project_names.get(project_id) or project_id,
                    "first_activity_at": seen_at,
                    "last_activity_at": seen_at,
                    "sources": set(),
                },
            )
            item["project_name"] = project_name or item["project_name"]
            item["first_activity_at"] = _min_time(item["first_activity_at"], seen_at)
            item["last_activity_at"] = _max_time(item["last_activity_at"], seen_at)
            item["sources"].add(source)

        snapshot_rows = _read_rows(
            conn,
            """
            SELECT id, project_id, project_name, user_id, device_id, workspace_name,
                   observed_at, received_at, payload_json
            FROM snapshots ORDER BY id ASC
            """,
        )
        for row in snapshot_rows:
            project_id = str(row["project_id"] or "")
            project_name = str(row["project_name"] or project_id)
            project_names[project_id] = project_name
            user_id = str(row["user_id"] or "").strip()
            if not user_id:
                continue
            seen_at = str(row["received_at"] or row["observed_at"] or _now())
            identity = _touch_identity(
                conn,
                provider="local",
                external_id=user_id,
                display_name=user_id,
                source="snapshot",
                seen_at=seen_at,
            )
            person_id = _ensure_local_or_agent_person(
                conn,
                identity,
                counterpart_provider="agent",
            )
            note_activity(person_id, project_id, project_name, seen_at, "local")

            collector_version = None
            try:
                payload = json.loads(row["payload_json"] or "{}")
                collector = payload.get("collector") or {}
                collector_version = collector.get("version") or collector.get("collector_version")
            except (TypeError, ValueError, json.JSONDecodeError):
                collector_version = None

            device_id = str(row["device_id"] or "").strip()
            if device_id:
                device_observations[device_id].append(
                    {
                        "identity_id": str(identity["identity_id"]),
                        "provider": "local",
                        "external_id": str(identity["external_id"]),
                        "person_id": person_id,
                        "seen_at": seen_at,
                        "project_id": project_id,
                        "project_name": project_name,
                        "workspace_name": str(row["workspace_name"] or ""),
                        "collector_version": str(collector_version or "") or None,
                    }
                )

        agent_rows = _read_rows(
            conn,
            """
            SELECT id, project_id, user_id, observed_at, received_at
            FROM agent_events ORDER BY id ASC
            """,
        )
        for row in agent_rows:
            user_id = str(row["user_id"] or "").strip()
            if not user_id:
                continue
            seen_at = str(row["received_at"] or row["observed_at"] or _now())
            identity = _touch_identity(
                conn,
                provider="agent",
                external_id=user_id,
                display_name=user_id,
                source="agent-event",
                seen_at=seen_at,
            )
            person_id = _ensure_local_or_agent_person(
                conn,
                identity,
                counterpart_provider="local",
            )
            project_id = str(row["project_id"] or "")
            note_activity(
                person_id,
                project_id,
                project_names.get(project_id) or project_id,
                seen_at,
                "agent",
            )

        remote_rows = _read_rows(
            conn,
            """
            SELECT id, project_id, provider, observed_at, received_at, data_json
            FROM remote_events ORDER BY id ASC
            """,
        )
        for row in remote_rows:
            provider = str(row["provider"] or "").strip().lower()
            if provider not in {"gitlab", "github"}:
                continue
            try:
                data = json.loads(row["data_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            external_id, display_name, email = _remote_actor(data)
            if not external_id:
                continue
            seen_at = str(row["received_at"] or row["observed_at"] or _now())
            identity = _touch_identity(
                conn,
                provider=provider,
                external_id=external_id,
                display_name=display_name,
                email=email,
                source=f"{provider}-event",
                seen_at=seen_at,
            )
            person_id = str(identity["person_id"]) if identity["person_id"] else None
            if not person_id and not identity["blocked_auto_link"] and email:
                person_id = _find_email_person(conn, email)
                if person_id:
                    _assign_identity(
                        conn,
                        str(identity["identity_id"]),
                        person_id,
                        confirmed=False,
                        reason="exact-email",
                    )
            project_id = str(row["project_id"] or "")
            note_activity(
                person_id,
                project_id,
                project_names.get(project_id) or project_id,
                seen_at,
                provider,
            )

        now = _now()
        for device_id, observations in device_observations.items():
            owner_keys: set[str] = set()
            for item in observations:
                owner_keys.add(
                    f"person:{item['person_id']}"
                    if item["person_id"]
                    else f"unresolved:{item['identity_id']}"
                )
            conflict = len(owner_keys) > 1
            person_ids = {
                str(item["person_id"])
                for item in observations
                if item["person_id"]
            }
            person_id = next(iter(person_ids)) if len(owner_keys) == 1 and len(person_ids) == 1 else None
            last_seen_at = None
            first_seen_at = None
            collector_version = None
            projects: dict[str, str] = {}
            workspaces: set[str] = set()
            conflict_refs: dict[tuple[str, str], dict[str, str]] = {}
            for item in observations:
                first_seen_at = _min_time(first_seen_at, item["seen_at"])
                if _max_time(last_seen_at, item["seen_at"]) == item["seen_at"]:
                    collector_version = item["collector_version"] or collector_version
                last_seen_at = _max_time(last_seen_at, item["seen_at"])
                projects[item["project_id"]] = item["project_name"]
                if item["workspace_name"]:
                    workspaces.add(item["workspace_name"])
                conflict_refs[(item["provider"], item["external_id"])] = {
                    "provider": item["provider"],
                    "external_id": item["external_id"],
                }
            refs = sorted(conflict_refs.values(), key=lambda item: (item["provider"], item["external_id"]))
            conn.execute(
                """
                INSERT INTO devices(
                    device_id, person_id, display_name, status, first_seen_at,
                    last_seen_at, collector_version, projects_json, workspace_count,
                    identity_conflict, conflict_identity_refs_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    person_id,
                    device_id,
                    _status(last_seen_at),
                    first_seen_at or last_seen_at or now,
                    last_seen_at,
                    collector_version,
                    json.dumps(
                        [
                            {"project_id": project_id, "project_name": name}
                            for project_id, name in sorted(projects.items())
                        ],
                        ensure_ascii=False,
                    ),
                    len(workspaces),
                    1 if conflict else 0,
                    json.dumps(refs if conflict else [], ensure_ascii=False),
                    now,
                    now,
                ),
            )

        for item in activities.values():
            conn.execute(
                """
                INSERT INTO person_projects(
                    person_id, project_id, project_name, first_activity_at,
                    last_activity_at, activity_sources_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["person_id"],
                    item["project_id"],
                    item["project_name"],
                    item["first_activity_at"],
                    item["last_activity_at"],
                    json.dumps(sorted(item["sources"]), ensure_ascii=False),
                    now,
                    now,
                ),
            )


def _public_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_id": item.get("identity_id"),
        "provider": item.get("provider"),
        "external_id": item.get("external_id"),
        "display_name": item.get("display_name"),
        "source": item.get("source"),
        "person_id": item.get("person_id"),
        "confirmed": bool(item.get("confirmed")),
        "blocked_auto_link": bool(item.get("blocked_auto_link")),
        "link_reason": item.get("link_reason"),
        "first_seen_at": item.get("first_seen_at"),
        "last_seen_at": item.get("last_seen_at"),
        "has_email": bool(item.get("email")),
    }


def list_identities(*, unassigned_only: bool = False) -> list[dict[str, Any]]:
    refresh_identity_projection()
    sql = """
        SELECT identity_id, provider, external_id, display_name, email, source,
               person_id, confirmed, blocked_auto_link, link_reason,
               first_seen_at, last_seen_at, created_at, updated_at
        FROM identities
    """
    if unassigned_only:
        sql += " WHERE person_id IS NULL"
    sql += " ORDER BY provider, lower(external_id)"
    with platform_config._db() as conn:
        rows = conn.execute(sql).fetchall()
    return [_public_identity(dict(row)) for row in rows]


def _public_device(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": item.get("device_id"),
        "display_name": item.get("display_name"),
        "person_id": item.get("person_id"),
        "status": item.get("status") or "unknown",
        "last_seen_at": item.get("last_seen_at"),
        "collector_version": item.get("collector_version"),
        "projects": json.loads(item.get("projects_json") or "[]"),
        "workspace_count": int(item.get("workspace_count") or 0),
        "identity_conflict": bool(item.get("identity_conflict")),
        "conflict_code": "device_identity_conflict" if item.get("identity_conflict") else None,
        "conflict_identities": json.loads(item.get("conflict_identity_refs_json") or "[]"),
    }


def list_devices() -> list[dict[str, Any]]:
    refresh_identity_projection()
    with platform_config._db() as conn:
        rows = conn.execute(
            """
            SELECT device_id, person_id, display_name, status, first_seen_at,
                   last_seen_at, collector_version, projects_json, workspace_count,
                   identity_conflict, conflict_identity_refs_json, created_at, updated_at
            FROM devices
            ORDER BY last_seen_at DESC, device_id
            """
        ).fetchall()
    return [_public_device(dict(row)) for row in rows]


def person_for_identity(provider: str, external_id: str) -> dict[str, Any] | None:
    refresh_identity_projection()
    provider = _provider(provider)
    external_id = _external_id(external_id)
    with platform_config._db() as conn:
        identity = _identity_row(conn, provider, external_id)
        if not identity or not identity["person_id"]:
            return None
        person = _person_row(conn, str(identity["person_id"]))
        if person is None:
            return None
        return dict(person)


def device_by_id(device_id: str) -> dict[str, Any] | None:
    refresh_identity_projection()
    with platform_config._db() as conn:
        row = conn.execute(
            """
            SELECT device_id, person_id, display_name, status, first_seen_at,
                   last_seen_at, collector_version, projects_json, workspace_count,
                   identity_conflict, conflict_identity_refs_json, created_at, updated_at
            FROM devices WHERE device_id=?
            """,
            (device_id,),
        ).fetchone()
    return _public_device(dict(row)) if row else None


def _identity_candidates(conn: sqlite3.Connection, identity: sqlite3.Row) -> list[dict[str, Any]]:
    if identity["person_id"] or identity["provider"] not in {"gitlab", "github"}:
        return []
    target = str(identity["external_id"] or identity["display_name"] or "").lower()
    if not target:
        return []
    candidates: list[dict[str, Any]] = []
    rows = conn.execute(
        """
        SELECT i.external_id, i.display_name, i.person_id, p.display_name AS person_name
        FROM identities i
        JOIN people p ON p.person_id=i.person_id
        WHERE i.provider IN ('local', 'agent') AND i.person_id IS NOT NULL
        """
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        person_id = str(row["person_id"])
        if person_id in seen:
            continue
        source = str(row["external_id"] or row["display_name"] or "").lower()
        if SequenceMatcher(None, target, source).ratio() < 0.72:
            continue
        seen.add(person_id)
        candidates.append(
            {
                "person_id": person_id,
                "display_name": row["person_name"],
                "reason": "identifier similar across providers",
                "confidence": "low",
            }
        )
    return candidates[:5]


def list_people() -> dict[str, Any]:
    refresh_identity_projection()
    with platform_config._db() as conn:
        people_rows = conn.execute(
            "SELECT person_id, display_name, status, created_at, updated_at FROM people ORDER BY display_name"
        ).fetchall()
        identity_rows = conn.execute(
            """
            SELECT identity_id, provider, external_id, display_name, email, source,
                   person_id, confirmed, blocked_auto_link, link_reason,
                   first_seen_at, last_seen_at, created_at, updated_at
            FROM identities ORDER BY provider, lower(external_id)
            """
        ).fetchall()
        device_rows = conn.execute(
            """
            SELECT device_id, person_id, display_name, status, first_seen_at,
                   last_seen_at, collector_version, projects_json, workspace_count,
                   identity_conflict, conflict_identity_refs_json, created_at, updated_at
            FROM devices ORDER BY last_seen_at DESC, device_id
            """
        ).fetchall()
        project_rows = conn.execute(
            """
            SELECT person_id, project_id, project_name, first_activity_at,
                   last_activity_at, activity_sources_json
            FROM person_projects
            ORDER BY last_activity_at DESC, project_name
            """
        ).fetchall()

        identities_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
        unresolved: list[sqlite3.Row] = []
        for row in identity_rows:
            if row["person_id"]:
                identities_by_person[str(row["person_id"])].append(_public_identity(dict(row)))
            else:
                unresolved.append(row)

        devices_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in device_rows:
            if row["person_id"]:
                devices_by_person[str(row["person_id"])].append(_public_device(dict(row)))

        projects_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in project_rows:
            projects_by_person[str(row["person_id"])].append(
                {
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "first_activity_at": row["first_activity_at"],
                    "last_activity_at": row["last_activity_at"],
                    "participation": _participation_state(row["last_activity_at"]),
                    "activity_sources": json.loads(row["activity_sources_json"] or "[]"),
                    "role": "participant",
                }
            )

        result: list[dict[str, Any]] = []
        for row in people_rows:
            person_id = str(row["person_id"])
            identities = identities_by_person.get(person_id, [])
            devices = devices_by_person.get(person_id, [])
            projects = projects_by_person.get(person_id, [])
            activity_sources = sorted(
                {
                    source
                    for project in projects
                    for source in project.get("activity_sources") or []
                }
                | {str(identity.get("provider")) for identity in identities if identity.get("provider")}
            )
            last_activity_at = None
            for identity in identities:
                last_activity_at = _max_time(last_activity_at, identity.get("last_seen_at"))
            for project in projects:
                last_activity_at = _max_time(last_activity_at, project.get("last_activity_at"))
            current_projects = [
                project for project in projects if project.get("participation") == "current"
            ]
            result.append(
                {
                    "person_id": person_id,
                    "display_name": row["display_name"],
                    "status": row["status"],
                    "identity_status": "confirmed" if any(item["confirmed"] for item in identities) else "observed",
                    "identities": identities,
                    "devices": devices,
                    "project_count": len(projects),
                    "projects": projects,
                    "current_projects": current_projects,
                    "last_activity_at": last_activity_at,
                    "activity_sources": activity_sources,
                }
            )

        for row in unresolved:
            result.append(
                {
                    "person_id": None,
                    "display_name": row["display_name"] or row["external_id"],
                    "status": "unconfirmed",
                    "identity_status": "unconfirmed",
                    "identities": [_public_identity(dict(row))],
                    "devices": [],
                    "project_count": 0,
                    "projects": [],
                    "current_projects": [],
                    "last_activity_at": row["last_seen_at"],
                    "activity_sources": [row["provider"]],
                    "possible_persons": _identity_candidates(conn, row),
                }
            )

        summary = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
        for row in device_rows:
            status = str(row["status"] or "unknown")
            summary[status] = summary.get(status, 0) + 1

    result.sort(key=lambda item: (item.get("person_id") is None, item.get("display_name") or ""))
    return {
        "count": len(result),
        "person_count": len(people_rows),
        "unconfirmed_identity_count": len(unresolved),
        "device_count": len(device_rows),
        "device_summary": summary,
        "people": result,
    }


def resolve_contributors(contributors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refresh_identity_projection()
    with platform_config._db() as conn:
        resolved: list[dict[str, Any]] = []
        for contributor in contributors:
            item = dict(contributor)
            refs = list(item.get("identity_refs") or [])
            if not refs:
                user_id = str(item.get("user_id") or "").strip()
                for source in item.get("source_types") or []:
                    if source == "local":
                        refs.append({"provider": "local", "external_id": user_id})
                    elif source == "agent":
                        refs.append({"provider": "agent", "external_id": user_id})
            person_ids: set[str] = set()
            public_refs: list[dict[str, Any]] = []
            for ref in refs:
                provider = str(ref.get("provider") or "").lower()
                external_id = str(ref.get("external_id") or "").strip()
                if provider not in SUPPORTED_IDENTITY_PROVIDERS or not external_id:
                    continue
                identity = _identity_row(conn, provider, external_id)
                public_ref = {
                    "provider": provider,
                    "external_id": external_id,
                    "display_name": ref.get("display_name") or external_id,
                }
                if identity and identity["person_id"]:
                    person_ids.add(str(identity["person_id"]))
                    public_ref["person_id"] = str(identity["person_id"])
                public_refs.append(public_ref)
            if len(person_ids) == 1:
                person_id = next(iter(person_ids))
                person = _person_row(conn, person_id)
                item["person_id"] = person_id
                item["identity_status"] = "resolved"
                if person:
                    item["display_name"] = person["display_name"]
            elif len(person_ids) > 1:
                item["person_id"] = None
                item["identity_status"] = "conflict"
            else:
                item["person_id"] = None
                item["identity_status"] = "unconfirmed"
            item["identities"] = public_refs
            resolved.append(item)

    grouped: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(resolved):
        key = (
            f"person:{item['person_id']}"
            if item.get("person_id")
            else f"raw:{index}:{json.dumps(item.get('identities') or [], sort_keys=True, ensure_ascii=False)}"
        )
        existing = grouped.get(key)
        if existing is None:
            clone = dict(item)
            for field in ("workspaces", "devices", "branches", "repositories", "agents", "source_types"):
                clone[field] = set(item.get(field) or [])
            clone["identities"] = {
                (ref.get("provider"), ref.get("external_id")): ref
                for ref in item.get("identities") or []
            }
            grouped[key] = clone
            continue
        for field in ("workspaces", "devices", "branches", "repositories", "agents", "source_types"):
            existing[field].update(item.get(field) or [])
        existing["identities"].update(
            {
                (ref.get("provider"), ref.get("external_id")): ref
                for ref in item.get("identities") or []
            }
        )
        for field in (
            "dirty_workspace_count",
            "changed_file_count",
            "attention_workspace_count",
            "agent_event_count",
            "remote_event_count",
        ):
            existing[field] = int(existing.get(field) or 0) + int(item.get(field) or 0)
        existing["workspace_count"] = len(existing["workspaces"])
        existing["latest_activity_at"] = _max_time(
            existing.get("latest_activity_at"), item.get("latest_activity_at")
        )

    output: list[dict[str, Any]] = []
    for item in grouped.values():
        for field in ("workspaces", "devices", "branches", "repositories", "agents", "source_types"):
            item[field] = sorted(item[field])
        item["identities"] = sorted(
            item["identities"].values(),
            key=lambda ref: (str(ref.get("provider") or ""), str(ref.get("external_id") or "")),
        )
        item["workspace_count"] = len(item["workspaces"])
        output.append(item)
    output.sort(key=lambda item: str(item.get("latest_activity_at") or ""), reverse=True)
    return output
