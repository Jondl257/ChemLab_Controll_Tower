"""SQLite-backed local repository; demo data is loaded only for a new database."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Generator

import pandas as pd

from config import DATABASE_PATH
from data.generator import generate_demo_data

DATETIME_COLUMNS = {
    "samples": ("received_at", "created_at"),
    "tasks": ("received_at", "deadline", "completed_at", "ordered_at"),
    "results": ("measured_at", "released_at"),
}


class Repository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DATABASE_PATH)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.db_path, timeout=30, check_same_thread=False
        )
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS repository_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS audit_events "
            "(event_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, "
            "entity_id TEXT NOT NULL, action TEXT NOT NULL, old_value TEXT, "
            "new_value TEXT, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, reason TEXT)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS submissions "
            "(submission_key TEXT PRIMARY KEY, sample_id TEXT NOT NULL, task_ids TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS local_users "
            "(username TEXT PRIMARY KEY COLLATE NOCASE, password_hash TEXT NOT NULL, "
            "role TEXT NOT NULL, employee_id TEXT, active INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL, created_by TEXT NOT NULL)"
        )
        self._connection.commit()
        initialized = self._connection.execute(
            "SELECT 1 FROM repository_meta WHERE key = 'initialized'"
        ).fetchone()
        if initialized is None:
            with self.transaction():
                for name, frame in generate_demo_data().items():
                    self._write_table(name, frame)
                self._connection.execute(
                    "INSERT INTO repository_meta (key, value) VALUES ('initialized', '1')"
                )
        self._migrate_legacy_tables()

    def _migrate_legacy_tables(self) -> None:
        required_columns = {
            "samples": {
                "sample_name": "TEXT",
                "notes": "TEXT",
                "created_at": "TEXT",
                "created_by": "TEXT NOT NULL DEFAULT 'DEMO-IMPORT'",
            },
            "tasks": {
                "ordered_at": "TEXT",
                "is_required": "INTEGER NOT NULL DEFAULT 1",
                "system_priority": "TEXT",
                "manual_priority": "TEXT",
                "manual_priority_reason": "TEXT",
                "manual_deadline_reason": "TEXT",
                "specification_version": "TEXT",
                "calculation_rule": "TEXT",
            },
            "results": {
                "result_version": "INTEGER NOT NULL DEFAULT 1",
                "is_current": "INTEGER NOT NULL DEFAULT 1",
                "validity_status": "TEXT NOT NULL DEFAULT 'nicht bewertet'",
                "review_status": "TEXT NOT NULL DEFAULT 'Prüfstatus historisch unbekannt'",
                "released_at": "TEXT",
                "specification_version": "TEXT",
                "calculation_rule": "TEXT",
                "recorded_by": "TEXT NOT NULL DEFAULT 'DEMO-IMPORT'",
                "released_by": "TEXT",
            },
        }
        with self._lock:
            for table, definitions in required_columns.items():
                existing = {
                    row[1]
                    for row in self._connection.execute(f'PRAGMA table_info("{table}")')
                }
                for column, definition in definitions.items():
                    if column not in existing:
                        self._connection.execute(
                            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                        )
            self._connection.execute(
                "UPDATE samples SET created_at=received_at WHERE created_at IS NULL"
            )
            self._connection.execute(
                "UPDATE tasks SET ordered_at=received_at WHERE ordered_at IS NULL"
            )
            self._connection.execute(
                "UPDATE tasks SET system_priority=priority WHERE system_priority IS NULL"
            )
            self._connection.execute(
                "UPDATE results SET review_status='freigegeben (synthetischer Import)', "
                "released_at=measured_at, released_by='DEMO-IMPORT' "
                "WHERE task_id IN (SELECT task_id FROM tasks WHERE status='Freigegeben') "
                "AND (review_status='Prüfstatus historisch unbekannt' OR review_status IS NULL)"
            )
            self._connection.execute(
                "UPDATE results SET is_current=1 WHERE is_current IS NULL"
            )
            self._connection.execute(
                "UPDATE results SET result_version=1 WHERE result_version IS NULL"
            )
            self._connection.execute(
                "UPDATE results SET validity_status='gültig (synthetischer Import)' "
                "WHERE validity_status IS NULL OR validity_status='nicht bewertet'"
            )
            self._connection.execute(
                "UPDATE results SET review_status='Prüfung erforderlich' "
                "WHERE review_status IS NULL AND task_id IN "
                "(SELECT task_id FROM tasks WHERE status='Prüfung erforderlich')"
            )
            self._connection.execute(
                "UPDATE results SET review_status='Historischer Demo-Prüfstatus unbekannt' "
                "WHERE review_status IS NULL"
            )
            self._connection.execute(
                "UPDATE results SET specification_version='DEMO-1' "
                "WHERE specification_version IS NULL"
            )
            self._connection.execute(
                "UPDATE results SET calculation_rule='Einzelwert-Demo' "
                "WHERE calculation_rule IS NULL"
            )
            self._connection.commit()

    def table(self, name: str) -> pd.DataFrame:
        with self._lock:
            exists = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            if exists is None:
                raise KeyError(f"Unbekannte Repository-Tabelle: {name}")
            frame = pd.read_sql_query(f'SELECT * FROM "{name}"', self._connection)
        for column in DATETIME_COLUMNS.get(name, ()):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], errors="coerce", format="mixed")
        return frame

    def replace(self, name: str, value: pd.DataFrame) -> None:
        with self._lock:
            self._write_table(name, value)

    def _write_table(self, name: str, value: pd.DataFrame) -> None:
        if not name.replace("_", "").isalnum():
            raise ValueError("Ungültiger Tabellenname.")
        frame = value.copy()
        column_types = {}
        for column in frame.columns:
            is_datetime = pd.api.types.is_datetime64_any_dtype(frame[column]) or any(
                isinstance(item, (date, datetime, pd.Timestamp))
                for item in frame[column].dropna().head(20)
            )
            if is_datetime:
                column_types[column] = "TEXT"
                frame[column] = frame[column].map(
                    lambda item: None
                    if item is None or pd.isna(item)
                    else pd.Timestamp(item).isoformat(sep=" ")
                )
            elif pd.api.types.is_bool_dtype(frame[column]):
                column_types[column] = "INTEGER"
            elif pd.api.types.is_integer_dtype(frame[column]):
                column_types[column] = "INTEGER"
            elif pd.api.types.is_numeric_dtype(frame[column]):
                column_types[column] = "REAL"
            else:
                column_types[column] = "TEXT"
        existing = {
            row[1] for row in self._connection.execute(f'PRAGMA table_info("{name}")')
        }
        if not existing:
            columns_ddl = ", ".join(
                f'"{column}" {column_types[column]}' for column in frame.columns
            )
            self._connection.execute(f'CREATE TABLE "{name}" ({columns_ddl})')
            existing = set(frame.columns)
        missing = set(frame.columns) - existing
        if missing:
            raise ValueError(f"Repository-Schema für {name} fehlt Spalten: {sorted(missing)}")
        ordered_columns = [
            row[1] for row in self._connection.execute(f'PRAGMA table_info("{name}")')
        ]
        if set(ordered_columns) != set(frame.columns):
            raise ValueError(f"Repository-Schema für {name} stimmt nicht mit dem Datenmodell überein.")
        was_in_transaction = self._connection.in_transaction
        self._connection.execute(f'DELETE FROM "{name}"')
        if not frame.empty:
            column_list = ", ".join(f'"{column}"' for column in ordered_columns)
            placeholders = ", ".join("?" for _ in ordered_columns)
            rows = [
                tuple(self._sqlite_value(value) for value in row)
                for row in frame[ordered_columns].itertuples(index=False, name=None)
            ]
            self._connection.executemany(
                f'INSERT INTO "{name}" ({column_list}) VALUES ({placeholders})',
                rows,
            )
        if not was_in_transaction:
            self._connection.commit()

    @staticmethod
    def _sqlite_value(value):
        if value is None or pd.isna(value):
            return None
        if isinstance(value, (date, datetime, pd.Timestamp)):
            return pd.Timestamp(value).isoformat(sep=" ")
        if hasattr(value, "item"):
            return value.item()
        return value

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def backup(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(target) as backup_connection:
            self._connection.backup(backup_connection)
        return target

    def log_event(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        old_value: str | None = None,
        new_value: str | None = None,
        reason: str | None = None,
    ) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._connection.execute(
                "INSERT INTO audit_events "
                "(entity_type, entity_id, action, old_value, new_value, actor, occurred_at, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entity_type, entity_id, action, old_value, new_value, actor, occurred_at, reason),
            )
            if not self._connection.in_transaction:
                self._connection.commit()

    def events(self, entity_id: str | None = None) -> list[dict]:
        with self._lock:
            if entity_id is None:
                rows = self._connection.execute(
                    "SELECT * FROM audit_events ORDER BY event_id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM audit_events WHERE entity_id=? ORDER BY event_id",
                    (entity_id,),
                ).fetchall()
            names = [item[1] for item in self._connection.execute(
                "PRAGMA table_info(audit_events)"
            ).fetchall()]
        return [dict(zip(names, row)) for row in rows]

    def submission(self, submission_key: str) -> tuple[str, list[str]] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT sample_id, task_ids FROM submissions WHERE submission_key=?",
                (submission_key,),
            ).fetchone()
        if row is None:
            return None
        return row[0], row[1].split(",") if row[1] else []

    def save_submission(self, submission_key: str, sample_id: str, task_ids: list[str]) -> None:
        self._connection.execute(
            "INSERT INTO submissions (submission_key, sample_id, task_ids) VALUES (?, ?, ?)",
            (submission_key, sample_id, ",".join(task_ids)),
        )

    def add_local_user(
        self,
        username: str,
        password_hash: str,
        role: str,
        employee_id: str | None,
        created_by: str,
    ) -> None:
        normalized = username.strip().casefold()
        if not normalized or len(normalized) > 100:
            raise ValueError("Benutzername muss 1 bis 100 Zeichen enthalten.")
        valid_roles = {"Laborant", "Laborleitung", "Administrator"}
        if role not in valid_roles:
            raise ValueError("Unbekannte Rolle.")
        employees = self.table("employees")
        if role == "Laborant":
            valid_employee = employees.loc[
                (employees.employee_id == employee_id) & (employees.role == "Laborant")
            ]
            if len(valid_employee) != 1:
                raise ValueError("Laborantenkonten müssen einem Laboranten zugeordnet sein.")
        elif role == "Laborleitung":
            valid_employee = employees.loc[
                (employees.employee_id == employee_id) & (employees.role == "Laborleiter")
            ]
            if len(valid_employee) != 1:
                raise ValueError("Leitungskonten müssen einem Laborleiter zugeordnet sein.")
        elif employee_id:
            raise ValueError("Administratorkonten werden keinem Labor-Mitarbeiter zugeordnet.")
        with self._lock:
            try:
                self._connection.execute(
                    "INSERT INTO local_users "
                    "(username, password_hash, role, employee_id, active, created_at, created_by) "
                    "VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (
                        normalized,
                        password_hash,
                        role,
                        employee_id,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        created_by,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Dieser Benutzername ist bereits vergeben.") from exc
            self.log_event(
                "local_user", normalized, "created", created_by,
                new_value=f"role={role}; employee={employee_id or '-'}",
            )
            self._connection.commit()

    def local_user(self, username: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT username, password_hash, role, employee_id, active "
                "FROM local_users WHERE username=? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        return dict(zip(("username", "password_hash", "role", "employee_id", "active"), row))

    def local_users(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT username, role, employee_id, active, created_at, created_by "
                "FROM local_users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        names = ("username", "role", "employee_id", "active", "created_at", "created_by")
        return [dict(zip(names, row)) for row in rows]

    def set_local_user_active(self, username: str, active: bool, actor: str) -> None:
        normalized = username.strip().casefold()
        with self.transaction():
            user = self._connection.execute(
                "SELECT role, active FROM local_users WHERE username=? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
            if user is None:
                raise ValueError("Lokales Benutzerkonto nicht gefunden.")
            if not active and user[0] == "Administrator":
                active_admins = self._connection.execute(
                    "SELECT COUNT(*) FROM local_users "
                    "WHERE role='Administrator' AND active=1 AND username<>? COLLATE NOCASE",
                    (normalized,),
                ).fetchone()[0]
                if active_admins == 0:
                    raise ValueError("Das letzte aktive Administratorkonto kann nicht deaktiviert werden.")
            if bool(user[1]) == active:
                state = "aktiv" if active else "deaktiviert"
                raise ValueError(f"Das Konto ist bereits {state}.")
            self._connection.execute(
                "UPDATE local_users SET active=? WHERE username=? COLLATE NOCASE",
                (int(active), normalized),
            )
            self.log_event(
                "local_user",
                normalized,
                "activated" if active else "deactivated",
                actor,
            )

    def reset_local_user_password(
        self, username: str, password_hash: str, actor: str
    ) -> None:
        normalized = username.strip().casefold()
        with self.transaction():
            updated = self._connection.execute(
                "UPDATE local_users SET password_hash=? WHERE username=? COLLATE NOCASE",
                (password_hash, normalized),
            )
            if updated.rowcount != 1:
                raise ValueError("Lokales Benutzerkonto nicht gefunden.")
            self.log_event(
                "local_user",
                normalized,
                "password_reset",
                actor,
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
