import pandas as pd
import pytest
from datetime import datetime
from data.generator import generate_demo_data
from data.repository import Repository
from domain.quality import assess
from domain.statistics import process_statistics
from domain.workflow import validate_transition
from services.workflow_service import WorkflowService
from services.auth_service import add_user, authenticate, reset_password


def test_generator_references_are_valid():
    d = generate_demo_data()
    assert set(d["tasks"].sample_id).issubset(set(d["samples"].sample_id))
    assert set(d["results"].task_id).issubset(set(d["tasks"].task_id))


def test_oos_logic():
    assert assess(0.9, 1, 2) == "OOS"
    assert assess(2.1, 1, 2) == "OOS"
    assert assess(1.5, 1, 2) == "PASS"


def test_statistics_known_values():
    s = process_statistics(pd.Series([1.0, 2.0, 3.0]), 0.0, 4.0)
    assert s["mean"] == 2 and s["cp"] is not None


def test_invalid_transition_is_blocked():
    with pytest.raises(ValueError):
        validate_transition("Offen", "Freigegeben")


def test_result_records_are_versioned_and_status_is_updated():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[repo.table("tasks").status == "In Bearbeitung"].iloc[0]
    before = len(repo.table("results").loc[repo.table("results").task_id == task.task_id])
    workflow.record_result(
        task.task_id,
        42.0,
        "Demo",
        actor="lab",
        actor_employee_id=task.assignee_id,
        actor_role="Laborant",
    )
    result_rows = repo.table("results").loc[repo.table("results").task_id == task.task_id]
    assert len(result_rows) == before + 1
    assert repo.table("tasks").loc[repo.table("tasks").task_id == task.task_id, "status"].iloc[0] == "Ergebnis erfasst"


def test_reassignment_to_another_employee_is_blocked():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[repo.table("tasks").status == "Offen"].iloc[0]
    workflow.transition(task.task_id, "Übernommen", "E-01", actor_role="Laborant", actor="lab")
    with pytest.raises(ValueError):
        workflow.transition(task.task_id, "Übernommen", "E-02", actor_role="Laborant", actor="other")


def test_lead_can_audit_manual_priority_and_deadline_changes():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[
        repo.table("tasks").status == "Offen"
    ].iloc[0]
    adjusted_deadline = datetime(2026, 10, 20, 16, 30)
    workflow.update_task_controls(
        task.task_id,
        actor="lead",
        actor_role="Laborleitung",
        reason="Produktionsplanung priorisiert",
        priority="Kritisch",
        deadline_at=adjusted_deadline,
    )
    adjusted = repo.table("tasks").loc[
        repo.table("tasks").task_id == task.task_id
    ].iloc[0]
    assert adjusted.priority == "Kritisch"
    assert adjusted.manual_priority == "Kritisch"
    assert adjusted.deadline == pd.Timestamp(adjusted_deadline)
    events = repo.events(task.task_id)
    assert [event["action"] for event in events][-2:] == [
        "priority_changed", "deadline_changed"
    ]
    assert all(event["reason"] == "Produktionsplanung priorisiert" for event in events[-2:])

    workflow.update_task_controls(
        task.task_id,
        actor="lead",
        actor_role="Laborleitung",
        reason="Manuelle Priorität nicht mehr erforderlich",
        priority="Systemvorschlag",
    )
    restored = repo.table("tasks").loc[
        repo.table("tasks").task_id == task.task_id
    ].iloc[0]
    assert restored.priority == restored.system_priority
    assert pd.isna(restored.manual_priority)


def test_priority_deadline_changes_require_lab_lead_and_reason():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task_id = repo.table("tasks").loc[
        repo.table("tasks").status == "Offen"
    ].iloc[0].task_id
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.update_task_controls(
            task_id,
            actor="lab",
            actor_role="Laborant",
            reason="not allowed",
            priority="Hoch",
        )
    with pytest.raises(ValueError, match="Begründung"):
        workflow.update_task_controls(
            task_id,
            actor="lead",
            actor_role="Laborleitung",
            reason="",
            priority="Hoch",
        )


def test_lead_can_reassign_claimed_task_with_reason():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[
        repo.table("tasks").status == "Offen"
    ].iloc[0]
    workflow.transition(
        task.task_id,
        "Übernommen",
        "E-01",
        actor_role="Laborant",
        actor="lab-one",
    )
    workflow.reassign_task(
        task.task_id,
        "E-02",
        actor="lead",
        actor_role="Laborleitung",
        reason="Schichtübergabe",
    )
    reassigned = repo.table("tasks").loc[
        repo.table("tasks").task_id == task.task_id
    ].iloc[0]
    assert reassigned.assignee_id == "E-02"
    assert reassigned.status == "Übernommen"
    assert repo.events(task.task_id)[-1]["reason"] == "Schichtübergabe"
    with pytest.raises(ValueError, match="Begründung"):
        workflow.reassign_task(
            task.task_id,
            "E-01",
            actor="lead",
            actor_role="Laborleitung",
            reason="",
        )


def test_lead_can_reopen_cancelled_task_but_not_released_task():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[
        repo.table("tasks").status == "Offen"
    ].iloc[0]
    workflow.transition(
        task.task_id,
        "Abgebrochen",
        actor="lead",
        actor_role="Laborleitung",
    )
    workflow.reopen_cancelled_task(
        task.task_id,
        actor="lead",
        actor_role="Laborleitung",
        reason="Abbruch irrtümlich erfolgt",
    )
    reopened = repo.table("tasks").loc[
        repo.table("tasks").task_id == task.task_id
    ].iloc[0]
    assert reopened.status == "Offen"
    assert pd.isna(reopened.assignee_id)
    assert repo.events(task.task_id)[-1]["action"] == "reopened"

    released_task = repo.table("tasks").loc[
        repo.table("tasks").status == "Freigegeben"
    ].iloc[0]
    with pytest.raises(ValueError, match="Nur abgebrochene"):
        workflow.reopen_cancelled_task(
            released_task.task_id,
            actor="lead",
            actor_role="Laborleitung",
            reason="Nicht zulässig",
        )


def test_sample_creation_is_multi_order_atomic_and_idempotent():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    initial_samples = len(repo.table("samples"))
    initial_tasks = len(repo.table("tasks"))
    parameters = {
        "product_id": "P-001",
        "sample_type": "Rohstoff",
        "methods": ["M-GC", "M-KF", "M-MP", "M-SENS"],
        "received_at": datetime(2026, 10, 13, 9, 15),
        "batch_id": "",
        "sample_name": "",
        "submission_key": "unique-browser-submit",
    }
    parameters.update(actor="lead", actor_role="Laborleitung")
    created = workflow.create_sample(**parameters)
    assert len(repo.table("samples")) == initial_samples + 1
    new_tasks = repo.table("tasks").tail(4)
    assert len(repo.table("tasks")) == initial_tasks + 4
    assert new_tasks.sample_id.nunique() == 1
    assert new_tasks.task_id.nunique() == 4
    sample = repo.table("samples").iloc[-1]
    assert pd.isna(sample.batch_id) and pd.isna(sample.sample_name)
    assert workflow.create_sample(**parameters) == created
    assert len(repo.table("samples")) == initial_samples + 1
    assert len(repo.table("tasks")) == initial_tasks + 4


def test_required_method_omission_requires_reason_and_lab_lead():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    params = {
        "product_id": "P-001",
        "sample_type": "Entwicklungsprobe",
        "methods": ["M-GC", "M-KF", "M-SENS"],
        "received_at": datetime.now(),
        "actor": "lead",
    }
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.create_sample(**params, actor_role="Laborant")
    with pytest.raises(ValueError, match="Pflichtanalysen"):
        workflow.create_sample(**params, actor_role="Laborleitung")
    sample_id, tasks = workflow.create_sample(
        **params, actor_role="Laborleitung", omission_reason="Demo-Prüfung"
    )
    assert len(tasks) == 3
    assert repo.table("tasks").loc[repo.table("tasks").sample_id == sample_id, "is_required"].sum() == 3
    assert any(event["action"] == "required_analyses_omitted" for event in repo.events(sample_id))


def test_sqlite_retains_changes_after_repository_reopen_and_backup(tmp_path):
    db_path = tmp_path / "lab.sqlite3"
    repo = Repository(db_path)
    workflow = WorkflowService(repo)
    sample_id, task_ids = workflow.create_sample(
        product_id="P-003",
        sample_type="Sonderprobe",
        methods=["M-AT", "M-MP"],
        received_at=datetime(2026, 10, 13, 10),
        actor="lead",
        actor_role="Laborleitung",
    )
    backup_path = repo.backup(tmp_path / "backup.sqlite3")
    repo.close()
    reopened = Repository(db_path)
    assert sample_id in set(reopened.table("samples").sample_id)
    assert set(task_ids).issubset(set(reopened.table("tasks").task_id))
    backup = Repository(backup_path)
    assert sample_id in set(backup.table("samples").sample_id)


def test_transaction_rolls_back_failed_related_writes():
    repo = Repository(":memory:")
    before = repo.table("samples")
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.replace("samples", before.iloc[1:].copy())
            raise RuntimeError("synthetic rollback check")
    assert len(repo.table("samples")) == len(before)


def test_local_accounts_use_password_hashes_and_database_roles():
    repo = Repository(":memory:")
    add_user(repo, "chemist", "secure-test-password", "Laborant", "E-01")
    user = repo.local_user("CHEMIST")
    assert user is not None and user["password_hash"] != "secure-test-password"
    assert authenticate(repo, "chemist", "secure-test-password")["role"] == "Laborant"
    assert authenticate(repo, "chemist", "wrong-password") is None


def test_admin_can_reset_password_and_deactivate_account_without_locking_out_admins():
    repo = Repository(":memory:")
    add_user(repo, "admin", "initial-admin-password", "Administrator", None)
    add_user(repo, "backup-admin", "another-admin-password", "Administrator", None)
    add_user(repo, "chemist", "initial-chemist-password", "Laborant", "E-01")

    reset_password(repo, "chemist", "replacement-password", "admin")
    assert authenticate(repo, "chemist", "initial-chemist-password") is None
    assert authenticate(repo, "chemist", "replacement-password") is not None

    repo.set_local_user_active("chemist", False, "admin")
    assert authenticate(repo, "chemist", "replacement-password") is None
    repo.set_local_user_active("chemist", True, "admin")
    assert authenticate(repo, "chemist", "replacement-password") is not None

    repo.set_local_user_active("admin", False, "backup-admin")
    with pytest.raises(ValueError, match="letzte aktive Administratorkonto"):
        repo.set_local_user_active("backup-admin", False, "backup-admin")
    events = repo.events("chemist")
    assert [event["action"] for event in events] == [
        "created", "password_reset", "deactivated", "activated"
    ]
    assert all("replacement-password" not in str(event.values()) for event in events)


def test_laborant_cannot_create_samples_or_release_results():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    with pytest.raises(ValueError):
        workflow.create_sample(
            product_id="P-001",
            sample_type="Endprodukt",
            methods=["M-GC", "M-KF", "M-MP", "M-SENS"],
            received_at=datetime.now(),
            actor="lab",
            actor_role="Laborant",
        )
    task = repo.table("tasks").loc[
        repo.table("tasks").status == "Prüfung erforderlich"
    ].iloc[0]
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.transition(task.task_id, "Freigegeben", actor="chemist", actor_role="Laborant")
    assert repo.table("tasks").loc[
        repo.table("tasks").task_id == task.task_id, "status"
    ].iloc[0] == "Prüfung erforderlich"


def test_workflow_actions_require_an_explicit_actor_and_role():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    task = repo.table("tasks").loc[
        repo.table("tasks").status == "Offen"
    ].iloc[0]
    with pytest.raises(TypeError):
        workflow.transition(task.task_id, "Abgebrochen", actor="someone")
    with pytest.raises(TypeError):
        workflow.record_result(task.task_id, 12.0, actor="someone")
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.transition(
            task.task_id, "Abgebrochen", actor="lab", actor_role="Laborant"
        )
    with pytest.raises(ValueError, match="Ergebnisstatus"):
        workflow.transition(
            task.task_id, "Ergebnis erfasst", actor="lab", actor_role="Laborant"
        )
