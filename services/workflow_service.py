from datetime import datetime
import pandas as pd
from domain.enums import TaskStatus
from domain.quality import assess
from domain.workflow import validate_transition
from data.master_data import PLANS

class WorkflowService:
    def __init__(self, repo): self.repo=repo
    def transition(self, task_id, target, employee_id=None):
        tasks=self.repo.table("tasks").copy(); i=tasks.index[tasks.task_id==task_id]
        if len(i)!=1: raise ValueError("Analyseauftrag nicht gefunden")
        idx=i[0]; validate_transition(tasks.at[idx,"status"],target)
        tasks.at[idx,"status"]=target
        if target==TaskStatus.RELEASED.value: tasks.at[idx,"completed_at"]=datetime.now()
        if employee_id: tasks.at[idx,"assignee_id"]=employee_id
        self.repo.replace("tasks",tasks)
    def record_result(self, task_id, value, comment=""):
        tasks=self.repo.table("tasks"); row=tasks.loc[tasks.task_id==task_id]
        if len(row)!=1: raise ValueError("Analyseauftrag nicht gefunden")
        task=row.iloc[0]; validate_transition(task.status,TaskStatus.RESULT_RECORDED.value)
        methods=self.repo.table("methods"); method=methods.loc[methods.method_id==task.method_id].iloc[0]
        _, target, lsl, usl, _ = next(item for item in PLANS[task.product_id] if item[0] == task.method_id)
        old=self.repo.table("results").copy(); spec=old.loc[old.task_id==task_id]
        values=[float(value),assess(float(value),lsl,usl),datetime.now(),comment]
        if spec.empty:
            new_id=f"R-{len(old)+1:05d}"
            old.loc[len(old)]=[new_id,task_id,method.parameter,values[0],method.unit,target,lsl,usl,values[1],values[2],values[3]]
        else:
            old.loc[old.task_id==task_id,["value","quality_status","measured_at","comment"]]=values
        self.repo.replace("results",old); self.transition(task_id,TaskStatus.RESULT_RECORDED.value)
