import pandas as pd
from domain.statistics import process_statistics
from domain.enums import DeadlineStatus, TaskPriority, TaskStatus


def task_view(repo):
    t = repo.table("tasks").merge(repo.table("samples")[["sample_id", "sample_type", "batch_id"]], on="sample_id")
    t = t.merge(repo.table("products")[["product_id", "product", "product_class"]], on="product_id")
    t = t.merge(repo.table("methods")[["method_id", "method"]], on="method_id")
    t = t.merge(repo.table("employees")[["employee_id", "employee"]], left_on="assignee_id", right_on="employee_id", how="left")
    now = pd.Timestamp.now()
    t["remaining_hours"] = (t.deadline - now).dt.total_seconds() / 3600
    t["deadline_status"] = pd.Series("im Zeitplan", index=t.index, dtype="object")
    t.loc[t.status.isin([TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value]), "deadline_status"] = DeadlineStatus.COMPLETED.value
    t.loc[(t.remaining_hours < 0) & ~t.status.isin([TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value]), "deadline_status"] = DeadlineStatus.OVERDUE.value
    sla_hours = (t.deadline - t.ordered_at).dt.total_seconds() / 3600
    t.loc[(t.remaining_hours > 0) & (t.remaining_hours <= sla_hours * 0.20), "deadline_status"] = DeadlineStatus.SOON.value
    return t


def queue_records(tasks):
    rows = tasks.round({"remaining_hours": 1}).to_dict("records")
    for row in rows:
        row["id"] = row["task_id"]
        if row["status"] in (TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value):
            row["deadline"] = "-"
        row["deadline_status"] = row.get("deadline_status", DeadlineStatus.ON_TIME.value)
    return rows


def queue_masks(tasks, now=None):
    today = pd.Timestamp(now or pd.Timestamp.now()).normalize()
    active_statuses = [TaskStatus.OPEN.value, TaskStatus.CLAIMED.value, TaskStatus.IN_PROGRESS.value, TaskStatus.RESULT_RECORDED.value, TaskStatus.REVIEW_REQUIRED.value]
    masks = {
        "open": tasks.status.isin(active_statuses),
        "overdue": (tasks.remaining_hours < 0) & ~tasks.status.isin([TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value]),
        "progress": tasks.status.eq(TaskStatus.IN_PROGRESS.value),
        "completed": tasks.status.eq(TaskStatus.RELEASED.value) & tasks.completed_at.dt.normalize().eq(today),
        "review": tasks.status.eq(TaskStatus.REVIEW_REQUIRED.value),
        "cancelled": tasks.status.eq(TaskStatus.CANCELLED.value),
        "critical": tasks.priority.eq(TaskPriority.CRITICAL.value) & tasks.status.isin(active_statuses),
        "active": tasks.status.isin(active_statuses),
    }
    return masks


def result_view(repo):
    return repo.table("results").merge(
        task_view(repo)[[
            "task_id", "sample_id", "batch_id", "product", "product_class",
            "method", "sample_type", "priority", "status", "deadline", "instrument_id",
        ]],
        on="task_id",
    )


def sample_quality_view(repo):
    samples = repo.table("samples").merge(
        repo.table("products")[["product_id", "product"]],
        on="product_id",
    )
    tasks = task_view(repo)
    results = result_view(repo)
    omitted_samples = {
        event["entity_id"]
        for event in repo.events()
        if event["entity_type"] == "sample"
        and event["action"] == "required_analyses_omitted"
    }
    oos_cases = repo.table("oos_cases")
    case_status_by_result = (
        oos_cases.set_index("result_id").status.to_dict()
        if not oos_cases.empty
        else {}
    )
    rows = []
    for sample in samples.itertuples():
        sample_tasks = tasks.loc[tasks.sample_id == sample.sample_id]
        task_ids = set(sample_tasks.task_id)
        current_results = results.loc[
            results.task_id.isin(task_ids) & results.is_current.astype(bool)
        ]
        current_oos = current_results.loc[current_results.quality_status.eq("OOS")]
        oos_requires_investigation = any(
            case_status_by_result.get(result_id) != "Abgeschlossen"
            for result_id in current_oos.result_id
        )
        required_tasks = sample_tasks.loc[sample_tasks.is_required.astype(bool)]
        required_missing = not required_tasks.empty and (
            not required_tasks.status.eq(TaskStatus.RELEASED.value).all()
            or not required_tasks.task_id.isin(current_results.task_id).all()
        )
        all_tasks_complete = (
            not sample_tasks.empty
            and sample_tasks.status.eq(TaskStatus.RELEASED.value).all()
            and set(sample_tasks.task_id).issubset(set(current_results.task_id))
            and current_results.loc[
                current_results.task_id.isin(task_ids), "review_status"
            ].astype(str).str.startswith("freigegeben").all()
            and current_results.loc[
                current_results.task_id.isin(task_ids), "validity_status"
            ].astype(str).str.startswith("gültig").all()
        )
        if oos_requires_investigation:
            assessment = "OOS – Untersuchung erforderlich"
        elif not current_oos.empty:
            assessment = "OOS – Fall abgeschlossen; Ergebnis bleibt OOS"
        elif sample.sample_id in omitted_samples:
            assessment = "Nicht bewertbar – Pflichtanalyse ausgelassen"
        elif required_missing or not all_tasks_complete:
            assessment = "Nicht abschließend bewertbar"
        elif current_results.quality_status.eq("GRENZNAH").any():
            assessment = "Grenznah – fachliche Bewertung erforderlich"
        elif current_results.quality_status.eq("PASS").all():
            assessment = "Konform (Demo; keine Freigabe)"
        else:
            assessment = "Bewertung erforderlich"
        rows.append({
            "sample_id": sample.sample_id,
            "product": sample.product,
            "sample_type": sample.sample_type,
            "batch_id": sample.batch_id,
            "analysis_count": len(sample_tasks),
            "required_count": int(sample_tasks.is_required.astype(bool).sum()),
            "released_count": int(sample_tasks.status.eq(TaskStatus.RELEASED.value).sum()),
            "oos_count": int(current_results.quality_status.eq("OOS").sum()),
            "oos_open_case_count": sum(
                case_status_by_result.get(result_id) != "Abgeschlossen"
                for result_id in current_oos.result_id
            ),
            "oos_closed_case_count": sum(
                case_status_by_result.get(result_id) == "Abgeschlossen"
                for result_id in current_oos.result_id
            ),
            "assessment": assessment,
        })
    return pd.DataFrame(rows)


def statistics(
    repo,
    product=None,
    parameter=None,
    method=None,
    start_date=None,
    end_date=None,
    quality_status=None,
    sample_type=None,
):
    r = result_view(repo)
    r = r.loc[r.is_current.astype(bool) & r.review_status.astype(str).str.startswith("freigegeben")].copy()
    r = r[(r["product"] == product) if product else pd.Series(True, index=r.index)]
    if method:
        r = r[r.method == method]
    if sample_type:
        r = r[r.sample_type == sample_type]
    if parameter:
        r = r[r.parameter == parameter]
    if quality_status:
        r = r[r.quality_status == quality_status]
    if start_date:
        start = pd.Timestamp(start_date)
        r = r[r.measured_at >= start]
    if end_date:
        end_exclusive = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
        r = r[r.measured_at < end_exclusive]
    if start_date and end_date and pd.Timestamp(start_date) > pd.Timestamp(end_date):
        raise ValueError("Der Starttag darf nicht nach dem Endtag liegen.")
    if r.empty:
        return r, process_statistics(pd.Series(dtype=float), None, None)

    bounds = r[["lsl", "usl"]].drop_duplicates()
    suitable_for_capability = (
        len(r) >= 30
        and r.method.nunique() == 1
        and r.sample_type.nunique() == 1
        and r.unit.nunique() == 1
        and len(bounds) == 1
    )
    lsl, usl = r.lsl.iloc[0], r.usl.iloc[0]
    summary = process_statistics(r.value, lsl, usl)
    if not suitable_for_capability:
        summary["cp"] = None
        summary["cpk"] = None
        summary["ucl"] = None
        summary["lcl"] = None
    return r, summary
