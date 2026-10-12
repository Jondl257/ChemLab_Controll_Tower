import pandas as pd
from domain.statistics import process_statistics
from domain.enums import TaskStatus

def task_view(repo):
    t=repo.table("tasks").merge(repo.table("samples")[["sample_id","sample_type","batch_id"]],on="sample_id").merge(repo.table("products")[["product_id","product","product_class"]],on="product_id").merge(repo.table("methods")[["method_id","method"]],on="method_id").merge(repo.table("employees")[["employee_id","employee"]],left_on="assignee_id",right_on="employee_id",how="left")
    now=pd.Timestamp.now(); t["remaining_hours"]=(t.deadline-now).dt.total_seconds()/3600; return t

def queue_records(tasks):
    rows=tasks.round({"remaining_hours":1}).to_dict("records")
    for row in rows:
        if row["status"] in (TaskStatus.RELEASED.value, TaskStatus.CANCELLED.value):
            row["deadline"]="-"
    return rows

def queue_masks(tasks, now=None):
    today=pd.Timestamp(now or pd.Timestamp.now()).normalize()
    return {
        "open": tasks.status.isin([TaskStatus.OPEN.value,TaskStatus.CLAIMED.value,TaskStatus.IN_PROGRESS.value]),
        "overdue": (tasks.remaining_hours<0)&~tasks.status.isin([TaskStatus.RELEASED.value,TaskStatus.CANCELLED.value]),
        "progress": tasks.status.eq(TaskStatus.IN_PROGRESS.value),
        "completed": tasks.status.eq(TaskStatus.RELEASED.value)&tasks.completed_at.dt.normalize().eq(today),
    }
def result_view(repo):
    return repo.table("results").merge(task_view(repo)[["task_id","product","product_class","method","sample_type","priority","status","deadline"]],on="task_id")
def statistics(repo, product=None, parameter=None):
    r=result_view(repo); r=r[(r["product"]==product) if product else pd.Series(True,index=r.index)]
    if parameter: r=r[r.parameter==parameter]
    if r.empty:return r,process_statistics(pd.Series(dtype=float),None,None)
    return r,process_statistics(r.value,r.lsl.iloc[0],r.usl.iloc[0])
