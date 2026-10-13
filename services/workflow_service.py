"""Transactional sample, order, measurement, and review operations."""
from datetime import datetime
import math
from uuid import uuid4

import pandas as pd

from config import deadline
from data.master_data import PLANS
from domain.enums import Role, TaskPriority, TaskStatus
from domain.quality import assess
from domain.workflow import validate_transition

SAMPLE_TYPES = (
    "Rohstoff",
    "Zwischenprodukt",
    "Endprodukt",
    "Entwicklungsprobe",
    "Stabilitätsprobe",
    "Sonderprobe",
)


def _next_id(frame: pd.DataFrame, column: str, prefix: str, width: int) -> str:
    numbers = [
        int(value[len(prefix):])
        for value in frame[column].dropna().astype(str)
        if value.startswith(prefix) and value[len(prefix):].isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1:0{width}d}"


def _priority_for(order_type: str) -> str:
    return "Hoch" if order_type == "Produktion dringend" else "Normal"


class WorkflowService:
    def __init__(self, repo):
        self.repo = repo

    def create_sample(
        self,
        *,
        product_id: str,
        sample_type: str,
        methods: list[str],
        received_at: datetime,
        batch_id: str | None = None,
        sample_name: str | None = None,
        notes: str | None = None,
        order_type: str = "Routine",
        actor_role: str,
        actor: str,
        omission_reason: str | None = None,
        submission_key: str | None = None,
    ) -> tuple[str, list[str]]:
        key = submission_key or str(uuid4())
        if actor_role != Role.LABORLEITUNG.value:
            raise ValueError("In dieser vorläufigen Rollenregel legt die Laborleitung Proben und Aufträge an.")
        normalized_methods = list(dict.fromkeys(methods))
        if not normalized_methods:
            raise ValueError("Mindestens eine Analysemethode muss ausgewählt sein.")
        if sample_type not in SAMPLE_TYPES:
            raise ValueError("Bitte eine gültige Probenart auswählen.")
        if order_type not in ("Routine", "Produktion dringend", "Stabilitätsprobe"):
            raise ValueError("Bitte eine gültige Demo-Auftragsart auswählen.")
        try:
            received_at = pd.Timestamp(received_at).to_pydatetime()
        except (TypeError, ValueError):
            raise ValueError("Bitte ein gültiges Probeneingangsdatum angeben.") from None
        if pd.isna(received_at):
            raise ValueError("Bitte ein gültiges Probeneingangsdatum angeben.")

        products = self.repo.table("products")
        product_rows = products.loc[products.product_id == product_id]
        if len(product_rows) != 1:
            raise ValueError("Produkt nicht gefunden.")
        methods_table = self.repo.table("methods")
        known_methods = set(methods_table.method_id)
        if not set(normalized_methods).issubset(known_methods):
            raise ValueError("Eine ausgewählte Methode ist nicht vorhanden.")

        plan = PLANS[product_id]
        plan_methods = [item[0] for item in plan]
        missing_required = set(plan_methods) - set(normalized_methods)
        if missing_required and (
            actor_role != Role.LABORLEITUNG.value or not (omission_reason or "").strip()
        ):
            raise ValueError(
                "Pflichtanalysen dürfen nur durch die Laborleitung und mit Begründung abgewählt werden."
            )

        with self.repo.transaction():
            previous = self.repo.submission(key)
            if previous is not None:
                return previous

            samples = self.repo.table("samples")
            tasks = self.repo.table("tasks")
            sample_id = _next_id(samples, "sample_id", "S-", 5)
            priority = _priority_for(order_type)
            order_moment = datetime.now()
            tasks_to_add = []
            task_ids = []
            for method_id in normalized_methods:
                task_id = _next_id(pd.concat([tasks, pd.DataFrame(tasks_to_add)], ignore_index=True), "task_id", "A-", 5)
                specification = next((item for item in plan if item[0] == method_id), None)
                method = methods_table.loc[methods_table.method_id == method_id].iloc[0]
                is_required = method_id in plan_methods
                instrument_ids = method.eligible_instruments.split("|")
                tasks_to_add.append({
                    "task_id": task_id,
                    "sample_id": sample_id,
                    "product_id": product_id,
                    "method_id": method_id,
                    "received_at": received_at,
                    "deadline": deadline(order_moment, order_type),
                    "order_type": order_type,
                    "priority": priority,
                    "status": TaskStatus.OPEN.value,
                    "assignee_id": None,
                    "instrument_id": None if instrument_ids == ["MANUELL"] else instrument_ids[0],
                    "ordered_at": order_moment,
                    "is_required": is_required,
                    "system_priority": priority,
                    "manual_priority": None,
                    "manual_priority_reason": None,
                    "specification_version": "DEMO-1" if specification else None,
                    "calculation_rule": "Einzelwert-Demo" if specification else None,
                    "completed_at": None,
                })
            sample = {
                "sample_id": sample_id,
                "batch_id": batch_id.strip() if batch_id and batch_id.strip() else None,
                "product_id": product_id,
                "sample_type": sample_type,
                "received_at": received_at,
                "sample_name": (sample_name or "").strip() or None,
                "notes": (notes or "").strip() or None,
                "created_at": datetime.now(),
                "created_by": actor,
            }
            new_sample = pd.concat([samples, pd.DataFrame([sample])], ignore_index=True)
            new_tasks = pd.concat([tasks, pd.DataFrame(tasks_to_add)], ignore_index=True)
            self.repo.replace("samples", new_sample)
            self.repo.replace("tasks", new_tasks)
            if missing_required:
                omitted_names = methods_table.loc[
                    methods_table.method_id.isin(missing_required), "method"
                ].tolist()
                self.repo.log_event(
                    "sample",
                    sample_id,
                    "required_analyses_omitted",
                    actor,
                    new_value=", ".join(omitted_names),
                    reason=omission_reason.strip(),
                )
            self.repo.log_event("sample", sample_id, "created", actor, new_value=product_id)
            task_ids = [item["task_id"] for item in tasks_to_add]
            for task_id in task_ids:
                self.repo.log_event("analysis_task", task_id, "ordered", actor, new_value=sample_id)
            self.repo.save_submission(key, sample_id, task_ids)
        return sample_id, task_ids

    def transition(
        self,
        task_id: str,
        target: str,
        employee_id: str | None = None,
        *,
        actor_role: str,
        actor: str,
    ) -> None:
        with self.repo.transaction():
            tasks = self.repo.table("tasks")
            match = tasks.loc[tasks.task_id == task_id]
            if len(match) != 1:
                raise ValueError("Analyseauftrag nicht gefunden.")
            row = match.iloc[0]
            if target == TaskStatus.RESULT_RECORDED.value:
                raise ValueError("Der Ergebnisstatus kann nur durch die Messwerterfassung gesetzt werden.")
            validate_transition(row.status, target)
            if target == TaskStatus.CANCELLED.value and actor_role != Role.LABORLEITUNG.value:
                raise ValueError("Nur die Laborleitung darf einen Auftrag abbrechen.")
            if target == TaskStatus.OPEN.value and actor_role != Role.LABORLEITUNG.value:
                raise ValueError("Nur die Laborleitung darf einen Auftrag wiedereröffnen.")
            if target == TaskStatus.CLAIMED.value:
                if actor_role != Role.LABORANT.value:
                    raise ValueError("Nur ein Laborant kann einen Auftrag übernehmen.")
                if not employee_id:
                    raise ValueError("Für die Übernahme ist ein Mitarbeiter erforderlich.")
                if pd.notna(row.assignee_id) and row.assignee_id != employee_id:
                    raise ValueError("Der Auftrag ist bereits einem anderen Mitarbeiter zugewiesen.")
                employee = self.repo.table("employees")
                staff = employee.loc[employee.employee_id == employee_id]
                if len(staff) != 1 or staff.iloc[0].role != Role.LABORANT.value:
                    raise ValueError("Der ausgewählte Mitarbeiter ist kein Laborant.")
            if target == TaskStatus.RELEASED.value and actor_role != Role.LABORLEITUNG.value:
                raise ValueError("Nur die Laborleitung darf ein Ergebnis fachlich freigeben.")
            if target == TaskStatus.IN_PROGRESS.value and actor_role != Role.LABORANT.value:
                raise ValueError("Nur ein Laborant darf einen Auftrag starten.")
            if target == TaskStatus.REVIEW_REQUIRED.value and actor_role != Role.LABORANT.value:
                raise ValueError("Nur ein Laborant darf die fachliche Prüfung anfordern.")
            if target in (TaskStatus.IN_PROGRESS.value, TaskStatus.REVIEW_REQUIRED.value):
                if employee_id is None or row.assignee_id != employee_id:
                    raise ValueError("Nur der zugewiesene Laborant darf diesen Auftrag bearbeiten.")

            idx = match.index[0]
            old_status = row.status
            tasks.at[idx, "status"] = target
            if target == TaskStatus.RELEASED.value:
                tasks.at[idx, "completed_at"] = datetime.now()
            if employee_id:
                tasks.at[idx, "assignee_id"] = employee_id
            self.repo.replace("tasks", tasks)
            if target == TaskStatus.RELEASED.value:
                results = self.repo.table("results")
                current = results.loc[(results.task_id == task_id) & results.is_current.astype(bool)]
                if current.empty:
                    raise ValueError("Ohne maßgebliche Messung kann der Auftrag nicht freigegeben werden.")
                results.loc[current.index, "review_status"] = "freigegeben"
                results.loc[current.index, "released_at"] = datetime.now()
                results.loc[current.index, "released_by"] = actor
                self.repo.replace("results", results)
            self.repo.log_event(
                "analysis_task", task_id, "status_changed", actor,
                old_value=str(old_status), new_value=target,
            )

    def update_task_controls(
        self,
        task_id: str,
        *,
        actor: str,
        actor_role: str,
        reason: str,
        priority: str | None = None,
        deadline_at: datetime | str | None = None,
    ) -> None:
        if actor_role != Role.LABORLEITUNG.value:
            raise ValueError("Nur die Laborleitung darf Priorität oder Frist ändern.")
        if not (reason or "").strip():
            raise ValueError("Für eine manuelle Änderung ist eine Begründung erforderlich.")
        if priority is None and deadline_at is None:
            raise ValueError("Bitte mindestens eine neue Priorität oder Frist angeben.")
        if priority is not None and priority not in {
            item.value for item in TaskPriority
        } | {"Systemvorschlag"}:
            raise ValueError("Bitte eine gültige Priorität auswählen.")
        parsed_deadline = None
        if deadline_at is not None:
            try:
                parsed_deadline = pd.Timestamp(deadline_at).to_pydatetime()
            except (TypeError, ValueError):
                raise ValueError("Bitte eine gültige Frist angeben.") from None
            if pd.isna(parsed_deadline):
                raise ValueError("Bitte eine gültige Frist angeben.")

        with self.repo.transaction():
            tasks = self.repo.table("tasks")
            match = tasks.loc[tasks.task_id == task_id]
            if len(match) != 1:
                raise ValueError("Analyseauftrag nicht gefunden.")
            row = match.iloc[0]
            if row.status in (TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value):
                raise ValueError("Abgeschlossene oder abgebrochene Aufträge können nicht angepasst werden.")
            idx = match.index[0]
            if priority is not None:
                previous = str(row.priority)
                if priority == "Systemvorschlag":
                    new_priority = row.system_priority
                    tasks.at[idx, "manual_priority"] = None
                    tasks.at[idx, "manual_priority_reason"] = None
                else:
                    new_priority = priority
                    tasks.at[idx, "manual_priority"] = priority
                    tasks.at[idx, "manual_priority_reason"] = reason.strip()
                tasks.at[idx, "priority"] = new_priority
                if previous != str(new_priority):
                    self.repo.log_event(
                        "analysis_task",
                        task_id,
                        "priority_changed",
                        actor,
                        old_value=previous,
                        new_value=str(new_priority),
                        reason=reason.strip(),
                    )
            if parsed_deadline is not None:
                previous_deadline = pd.Timestamp(row.deadline).isoformat()
                new_deadline = pd.Timestamp(parsed_deadline).isoformat()
                tasks.at[idx, "deadline"] = parsed_deadline
                tasks.at[idx, "manual_deadline_reason"] = reason.strip()
                if previous_deadline != new_deadline:
                    self.repo.log_event(
                        "analysis_task",
                        task_id,
                        "deadline_changed",
                        actor,
                        old_value=previous_deadline,
                        new_value=new_deadline,
                        reason=reason.strip(),
                    )
            self.repo.replace("tasks", tasks)

    def reassign_task(
        self,
        task_id: str,
        employee_id: str,
        *,
        actor: str,
        actor_role: str,
        reason: str,
    ) -> None:
        if actor_role != Role.LABORLEITUNG.value:
            raise ValueError("Nur die Laborleitung darf Aufträge neu zuweisen.")
        if not (reason or "").strip():
            raise ValueError("Für eine Neuzuweisung ist eine Begründung erforderlich.")
        with self.repo.transaction():
            tasks = self.repo.table("tasks")
            match = tasks.loc[tasks.task_id == task_id]
            if len(match) != 1:
                raise ValueError("Analyseauftrag nicht gefunden.")
            row = match.iloc[0]
            if row.status not in (TaskStatus.CLAIMED.value, TaskStatus.IN_PROGRESS.value):
                raise ValueError("Nur übernommene oder in Bearbeitung befindliche Aufträge können neu zugewiesen werden.")
            employee = self.repo.table("employees")
            staff = employee.loc[
                (employee.employee_id == employee_id)
                & (employee.role == Role.LABORANT.value)
            ]
            if len(staff) != 1:
                raise ValueError("Die Neuzuweisung muss an einen gültigen Laboranten erfolgen.")
            previous = row.assignee_id
            if previous == employee_id:
                raise ValueError("Der Auftrag ist diesem Laboranten bereits zugewiesen.")
            tasks.at[match.index[0], "assignee_id"] = employee_id
            self.repo.replace("tasks", tasks)
            self.repo.log_event(
                "analysis_task",
                task_id,
                "reassigned",
                actor,
                old_value=str(previous),
                new_value=employee_id,
                reason=reason.strip(),
            )

    def reopen_cancelled_task(
        self,
        task_id: str,
        *,
        actor: str,
        actor_role: str,
        reason: str,
    ) -> None:
        if actor_role != Role.LABORLEITUNG.value:
            raise ValueError("Nur die Laborleitung darf einen Auftrag wiedereröffnen.")
        if not (reason or "").strip():
            raise ValueError("Für die Wiedereröffnung ist eine Begründung erforderlich.")
        with self.repo.transaction():
            tasks = self.repo.table("tasks")
            match = tasks.loc[tasks.task_id == task_id]
            if len(match) != 1:
                raise ValueError("Analyseauftrag nicht gefunden.")
            if match.iloc[0].status != TaskStatus.CANCELLED.value:
                raise ValueError("Nur abgebrochene Aufträge können wiedereröffnet werden.")
            results = self.repo.table("results")
            current_results = results.loc[
                (results.task_id == task_id) & results.is_current.astype(bool)
            ]
            if not current_results.empty:
                raise ValueError("Aufträge mit maßgeblichem Ergebnis müssen fachlich geprüft werden und können nicht wiedereröffnet werden.")
            idx = match.index[0]
            tasks.at[idx, "status"] = TaskStatus.OPEN.value
            tasks.at[idx, "assignee_id"] = None
            tasks.at[idx, "completed_at"] = None
            self.repo.replace("tasks", tasks)
            self.repo.log_event(
                "analysis_task",
                task_id,
                "reopened",
                actor,
                old_value=TaskStatus.CANCELLED.value,
                new_value=TaskStatus.OPEN.value,
                reason=reason.strip(),
            )

    def record_result(
        self,
        task_id: str,
        value: float,
        comment: str = "",
        *,
        actor_role: str,
        actor: str,
        actor_employee_id: str | None = None,
    ) -> str:
        if value is None or not math.isfinite(float(value)):
            raise ValueError("Der Messwert muss eine endliche Zahl sein.")
        with self.repo.transaction():
            tasks = self.repo.table("tasks")
            row = tasks.loc[tasks.task_id == task_id]
            if len(row) != 1:
                raise ValueError("Analyseauftrag nicht gefunden.")
            task = row.iloc[0]
            if actor_role != Role.LABORANT.value:
                raise ValueError("Nur ein Laborant darf Messwerte erfassen.")
            if actor_employee_id is None or task.assignee_id != actor_employee_id:
                raise ValueError("Messwerte darf nur der zugewiesene Laborant erfassen.")
            if task.status != TaskStatus.IN_PROGRESS.value:
                raise ValueError("Messwerte können nur während der Bearbeitung erfasst werden.")
            methods = self.repo.table("methods")
            method_rows = methods.loc[methods.method_id == task.method_id]
            if len(method_rows) != 1:
                raise ValueError("Methode des Analyseauftrags nicht gefunden.")
            method = method_rows.iloc[0]
            plan = next((item for item in PLANS[task.product_id] if item[0] == task.method_id), None)
            if plan is None:
                raise ValueError("Für diese Methode fehlt eine Demo-Spezifikation; Ergebnisaufnahme ist gesperrt.")
            _, target, lsl, usl, _ = plan
            if lsl is not None and usl is not None and lsl > usl:
                raise ValueError("Die hinterlegte Spezifikation ist ungültig.")
            numeric_value = float(value)
            results = self.repo.table("results")
            previous = results.loc[results.task_id == task_id]
            version = int(previous.result_version.max()) + 1 if not previous.empty else 1
            if not previous.empty:
                results.loc[previous.index, "is_current"] = False
            result_id = _next_id(results, "result_id", "R-", 5)
            result = {
                "result_id": result_id,
                "task_id": task_id,
                "parameter": method.parameter,
                "value": numeric_value,
                "unit": method.unit,
                "target": target,
                "lsl": lsl,
                "usl": usl,
                "quality_status": assess(numeric_value, lsl, usl),
                "measured_at": datetime.now(),
                "comment": comment or "",
                "result_version": version,
                "is_current": True,
                "validity_status": "gültig",
                "review_status": "Prüfung erforderlich",
                "released_at": None,
                "specification_version": "DEMO-1",
                "calculation_rule": "Einzelwert-Demo",
                "recorded_by": actor,
                "released_by": None,
            }
            results = pd.concat([results, pd.DataFrame([result])], ignore_index=True)
            self.repo.replace("results", results)
            idx = row.index[0]
            tasks.at[idx, "status"] = TaskStatus.RESULT_RECORDED.value
            self.repo.replace("tasks", tasks)
            self.repo.log_event(
                "analysis_task", task_id, "measurement_recorded", actor,
                new_value=f"{result_id}: {numeric_value} {method.unit}",
            )
        return result_id
