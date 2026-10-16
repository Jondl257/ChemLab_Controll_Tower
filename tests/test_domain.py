import pandas as pd
import pytest
from datetime import datetime
from data.generator import generate_demo_data
from data.repository import Repository
from domain.quality import assess
from domain.statistics import process_statistics
from domain.workflow import validate_transition
from services.analytics_service import sample_quality_view
from services.workflow_service import SAMPLE_TYPES, WorkflowService
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


def test_sample_quality_view_distinguishes_pass_oos_pending_near_limit_and_omissions():
    repo = Repository(":memory:")
    sample = repo.table("samples").iloc[[0]].copy()
    task = repo.table("tasks").loc[
        repo.table("tasks").sample_id == sample.iloc[0].sample_id
    ].iloc[[0]].copy()
    result = repo.table("results").loc[
        repo.table("results").task_id == task.iloc[0].task_id
    ].iloc[[0]].copy()
    task["status"] = "Freigegeben"
    task["is_required"] = 1
    result["is_current"] = 1
    result["quality_status"] = "PASS"
    result["validity_status"] = "gültig"
    result["review_status"] = "freigegeben"
    repo.replace("samples", sample)
    repo.replace("tasks", task)
    repo.replace("results", result)

    assessment = sample_quality_view(repo).iloc[0]
    assert assessment.assessment == "Konform (Demo; keine Freigabe)"

    result["quality_status"] = "OOS"
    task["status"] = "Prüfung erforderlich"
    result["review_status"] = "Prüfung erforderlich"
    repo.replace("tasks", task)
    repo.replace("results", result)
    assert sample_quality_view(repo).iloc[0].assessment == "OOS – Untersuchung erforderlich"

    result["quality_status"] = "PASS"
    task["status"] = "In Bearbeitung"
    result["review_status"] = "Prüfung erforderlich"
    repo.replace("tasks", task)
    repo.replace("results", result)
    assert sample_quality_view(repo).iloc[0].assessment == "Nicht abschließend bewertbar"

    task["status"] = "Freigegeben"
    result["quality_status"] = "GRENZNAH"
    result["review_status"] = "freigegeben"
    repo.replace("tasks", task)
    repo.replace("results", result)
    assert sample_quality_view(repo).iloc[0].assessment == "Grenznah – fachliche Bewertung erforderlich"

    repo.log_event(
        "sample",
        sample.iloc[0].sample_id,
        "required_analyses_omitted",
        "lead",
        reason="Demo-Ausnahme",
    )
    result["quality_status"] = "PASS"
    repo.replace("results", result)
    assert sample_quality_view(repo).iloc[0].assessment == (
        "Nicht bewertbar – Pflichtanalyse ausgelassen"
    )


def test_oos_case_open_and_close_preserve_result_and_update_sample_assessment():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    result = repo.table("results").loc[
        repo.table("results").quality_status == "OOS"
    ].iloc[0]
    sample_id = repo.table("tasks").set_index("task_id").loc[result.task_id, "sample_id"]

    case_id = workflow.open_oos_case(
        result.result_id,
        "Out-of-specification signal observed during review.",
        actor="lead",
        actor_role="Laborleitung",
    )
    case = repo.table("oos_cases").iloc[0]
    assert case.case_id == case_id
    assert case.result_id == result.result_id
    assert case.status == "Offen"
    assert sample_quality_view(repo).set_index("sample_id").loc[
        sample_id, "assessment"
    ] == "OOS – Untersuchung erforderlich"

    workflow.close_oos_case(
        case_id,
        root_cause="Demo cause documented.",
        corrective_action="Containment action recorded.",
        closure_rationale="Investigation complete for demonstration.",
        actor="lead",
        actor_role="Laborleitung",
    )
    closed = repo.table("oos_cases").iloc[0]
    assert closed.status == "Abgeschlossen"
    assert closed.closed_by == "lead"
    unchanged = repo.table("results").loc[
        repo.table("results").result_id == result.result_id
    ].iloc[0]
    assert unchanged.quality_status == "OOS"
    assert unchanged.review_status == result.review_status
    assessment = sample_quality_view(repo).set_index("sample_id").loc[sample_id]
    assert assessment.assessment == "OOS – Fall abgeschlossen; Ergebnis bleibt OOS"
    assert assessment.oos_open_case_count == 0
    assert assessment.oos_closed_case_count == 1
    assert [event["action"] for event in repo.events(case_id)] == ["opened", "closed"]


def test_oos_case_requires_lead_nonempty_reason_unique_result_and_complete_close():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    results = repo.table("results")
    oos_result = results.loc[results.quality_status == "OOS"].iloc[0]
    passing_result = results.loc[results.quality_status == "PASS"].iloc[0]
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.open_oos_case(
            oos_result.result_id,
            "Description",
            actor="lab",
            actor_role="Laborant",
        )
    with pytest.raises(ValueError, match="Erstbeschreibung"):
        workflow.open_oos_case(
            oos_result.result_id,
            "",
            actor="lead",
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="nur für ein OOS"):
        workflow.open_oos_case(
            passing_result.result_id,
            "Description",
            actor="lead",
            actor_role="Laborleitung",
        )

    case_id = workflow.open_oos_case(
        oos_result.result_id,
        "Description",
        actor="lead",
        actor_role="Laborleitung",
    )
    with pytest.raises(ValueError, match="bereits ein OOS-Fall"):
        workflow.open_oos_case(
            oos_result.result_id,
            "Duplicate",
            actor="lead",
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="Ursachenbewertung"):
        workflow.close_oos_case(
            case_id,
            root_cause="",
            corrective_action="Action",
            closure_rationale="Rationale",
            actor="lead",
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.close_oos_case(
            case_id,
            root_cause="Cause",
            corrective_action="Action",
            closure_rationale="Rationale",
            actor="lab",
            actor_role="Laborant",
        )


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


def test_specification_versions_are_immutable_and_snapshotted_to_new_samples():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    existing_sample = repo.table("samples").loc[
        repo.table("samples").product_id.eq("P-001")
    ].iloc[0]
    existing_sample_task = repo.table("tasks").loc[
        repo.table("tasks").sample_id.eq(existing_sample.sample_id)
        & repo.table("tasks").method_id.eq("M-GC")
    ].iloc[0]
    assert existing_sample.specification_version == "DEMO-1"
    old_target = existing_sample_task.target
    assert existing_sample_task.specification_version == "DEMO-1"

    version = workflow.create_specification_version(
        "P-001",
        "M-GC",
        target=99.6,
        lsl=98.8,
        usl=99.9,
        sigma=0.2,
        reason="Demo-Grenzen für Versionsprüfung",
        actor="lead",
        actor_role="Laborleitung",
    )
    assert version == "DEMO-2"
    old_task_after_version = repo.table("tasks").loc[
        repo.table("tasks").task_id.eq(existing_sample_task.task_id)
    ].iloc[0]
    assert old_task_after_version.target == old_target
    assert old_task_after_version.specification_version == "DEMO-1"

    active = repo.table("specifications").loc[
        repo.table("specifications").product_id.eq("P-001")
        & repo.table("specifications").active.astype(bool)
    ]
    assert set(active.version) == {"DEMO-2"}
    assert len(active) == len(
        repo.table("specifications").loc[
            repo.table("specifications").product_id.eq("P-001")
            & repo.table("specifications").version.eq("DEMO-1")
        ]
    )

    sample_id, task_ids = workflow.create_sample(
        product_id="P-001",
        sample_type="Rohstoff",
        methods=active.method_id.tolist(),
        received_at=datetime.now(),
        actor="lead",
        actor_role="Laborleitung",
    )
    new_task = repo.table("tasks").loc[
        repo.table("tasks").task_id.isin(task_ids)
        & repo.table("tasks").method_id.eq("M-GC")
    ].iloc[0]
    assert repo.table("samples").loc[
        repo.table("samples").sample_id.eq(sample_id), "specification_version"
    ].iloc[0] == "DEMO-2"
    assert (
        new_task.specification_version,
        new_task.target,
        new_task.lsl,
        new_task.usl,
        new_task.sigma,
    ) == ("DEMO-2", 99.6, 98.8, 99.9, 0.2)

    with repo.transaction():
        tasks = repo.table("tasks")
        task_idx = tasks.index[tasks.task_id.eq(new_task.task_id)][0]
        tasks.at[task_idx, "status"] = "In Bearbeitung"
        tasks.at[task_idx, "assignee_id"] = "E-01"
        repo.replace("tasks", tasks)
    result_id = workflow.record_result(
        new_task.task_id,
        99.7,
        actor="chemist",
        actor_employee_id="E-01",
        actor_role="Laborant",
    )
    result = repo.table("results").loc[
        repo.table("results").result_id.eq(result_id)
    ].iloc[0]
    assert result.specification_version == "DEMO-2"
    assert (result.target, result.lsl, result.usl) == (99.6, 98.8, 99.9)


def test_specification_versioning_requires_lab_lead_and_valid_complete_limits():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    parameters = {
        "target": 99.6,
        "lsl": 98.8,
        "usl": 99.9,
        "sigma": 0.2,
        "reason": "Demo version test",
        "actor": "lead",
    }
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.create_specification_version(
            "P-001", "M-GC", **parameters, actor_role="Laborant"
        )
    with pytest.raises(ValueError, match="Begründung"):
        workflow.create_specification_version(
            "P-001", "M-GC", **{**parameters, "reason": ""},
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="Untergrenze"):
        workflow.create_specification_version(
            "P-001", "M-GC", **{**parameters, "lsl": 100.0},
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="Streuung"):
        workflow.create_specification_version(
            "P-001", "M-GC", **{**parameters, "sigma": 0.0},
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="gehört nicht"):
        workflow.create_specification_version(
            "P-001", "M-NIR", **parameters, actor_role="Laborleitung"
        )


def test_sample_details_require_lead_and_record_each_change_with_reason():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    sample = repo.table("samples").iloc[0]
    old_name = sample.sample_name
    old_type = sample.sample_type
    new_type = next(value for value in SAMPLE_TYPES if value != old_type)
    workflow.update_sample_details(
        sample.sample_id,
        sample_name="Stabilität 2026-10",
        batch_id="CH-2026-007",
        notes="Lagerung bei 25 °C",
        sample_type=new_type,
        reason="Korrektur anhand Eingangsprotokoll",
        actor="lead",
        actor_role="Laborleitung",
    )
    updated = repo.table("samples").loc[
        repo.table("samples").sample_id == sample.sample_id
    ].iloc[0]
    assert updated.sample_name == "Stabilität 2026-10"
    assert updated.batch_id == "CH-2026-007"
    assert updated.notes == "Lagerung bei 25 °C"
    assert updated.sample_type == new_type
    changes = repo.events(sample.sample_id)
    assert [event["action"] for event in changes[-4:]] == [
        "sample_name_changed", "batch_id_changed", "notes_changed", "sample_type_changed"
    ]
    assert changes[-4]["old_value"] == (str(old_name) if pd.notna(old_name) else None)
    assert changes[-1]["old_value"] == old_type
    assert all(
        event["reason"] == "Korrektur anhand Eingangsprotokoll"
        for event in changes[-4:]
    )


def test_sample_details_reject_missing_reason_invalid_role_and_oversized_values():
    repo = Repository(":memory:")
    workflow = WorkflowService(repo)
    sample_id = repo.table("samples").iloc[0].sample_id
    with pytest.raises(ValueError, match="Laborleitung"):
        workflow.update_sample_details(
            sample_id,
            sample_name="Updated",
            batch_id=None,
            notes=None,
            sample_type="Sonderprobe",
            reason="Valid reason",
            actor="lab",
            actor_role="Laborant",
        )
    with pytest.raises(ValueError, match="Begründung"):
        workflow.update_sample_details(
            sample_id,
            sample_name="Updated",
            batch_id=None,
            notes=None,
            sample_type="Sonderprobe",
            reason="",
            actor="lead",
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="höchstens 200"):
        workflow.update_sample_details(
            sample_id,
            sample_name="x" * 201,
            batch_id=None,
            notes=None,
            sample_type="Sonderprobe",
            reason="Valid reason",
            actor="lead",
            actor_role="Laborleitung",
        )
    with pytest.raises(ValueError, match="gültige Probenart"):
        workflow.update_sample_details(
            sample_id,
            sample_name="Updated",
            batch_id=None,
            notes=None,
            sample_type="Ungültig",
            reason="Valid reason",
            actor="lead",
            actor_role="Laborleitung",
        )


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
