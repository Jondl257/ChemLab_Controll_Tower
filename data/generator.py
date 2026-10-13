from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from config import DEMO_DAYS, SEED, deadline
from data.master_data import PLANS, frames
from domain.enums import TaskStatus
from domain.quality import assess

def generate_demo_data(seed: int = SEED, now: datetime | None = None) -> dict:
    rng, master = np.random.default_rng(seed), frames()
    products, methods = master["products"], master["methods"].set_index("method_id")
    now = (now or datetime.now()).replace(microsecond=0)
    task_rows, result_rows, sample_rows, batch_no, task_no, result_no = [], [], [], 1, 1, 1
    statuses = [TaskStatus.RELEASED.value, TaskStatus.REVIEW_REQUIRED.value, TaskStatus.IN_PROGRESS.value, TaskStatus.CLAIMED.value, TaskStatus.OPEN.value]
    queue_statuses = (TaskStatus.OPEN.value, TaskStatus.CLAIMED.value, TaskStatus.IN_PROGRESS.value)
    visible_priorities = ("Normal", "Hoch", "Kritisch")
    queued_task_count = 0
    for day in range(DEMO_DAYS):
        age_days = DEMO_DAYS-day-1
        received = now - timedelta(days=age_days, hours=int(rng.integers(0,8)))
        for _ in range(int(rng.integers(2,5))):
            product = products.iloc[int(rng.integers(len(products)))]; batch_id=f"B-{batch_no:04d}"; batch_no += 1
            sample_id=f"S-{batch_no:04d}"; sample_type=rng.choice(["Zwischenprodukt","Endprodukt","Stabilitätsprobe"],p=[.30,.55,.15])
            sample_rows.append((sample_id,batch_id,product.product_id,sample_type,received))
            plan = PLANS[product.product_id]
            for method_id,target,lsl,usl,sigma in plan:
                method=methods.loc[method_id]; order_type=rng.choice(["Routine","Produktion dringend","Stabilitätsprobe"],p=[.66,.20,.14])
                # Historical samples are completed; recent samples form the live queue.
                status=rng.choice(statuses,p=[.46,.12,.12,.12,.18]) if age_days < 2 else TaskStatus.RELEASED.value
                system_priority = "Hoch" if order_type == "Produktion dringend" else "Normal"
                priority = system_priority
                if status in queue_statuses and queued_task_count < len(visible_priorities):
                    priority=visible_priorities[queued_task_count]
                    queued_task_count += 1
                assignee=None if status==TaskStatus.OPEN.value else f"E-{int(rng.integers(1,6)):02d}"
                instruments=method.eligible_instruments.split("|"); instr=None if instruments==["MANUELL"] else rng.choice(instruments)
                task_id=f"A-{task_no:05d}"; task_no+=1; due=deadline(received,order_type)
                task_rows.append((task_id,sample_id,product.product_id,method_id,received,due,order_type,priority,status,assignee,instr,received,True,system_priority,priority if priority != system_priority else None,"Synthetische Demo-Übersteuerung" if priority != system_priority else None,"DEMO-1","Einzelwert-Demo"))
                if status in [TaskStatus.RELEASED.value,TaskStatus.REVIEW_REQUIRED.value]:
                    drift = (day / DEMO_DAYS) * sigma * (1.5 if product.product_id=="P-004" else 0)
                    value=float(rng.normal(target+drift,sigma))
                    if rng.random()<.055: value=float(rng.choice([lsl-rng.uniform(.02,1)*max(sigma,1),usl+rng.uniform(.02,1)*max(sigma,1)]))
                    measured_at=min(now,received+timedelta(hours=int(rng.integers(1,30))))
                    result_rows.append((f"R-{result_no:05d}",task_id,method.parameter,value,method.unit,target,lsl,usl,assess(value,lsl,usl),measured_at,"Synthetischer Demo-Messwert",1,True,"gültig","freigegeben" if status==TaskStatus.RELEASED.value else "Prüfung erforderlich",measured_at if status==TaskStatus.RELEASED.value else None,"DEMO-1","Einzelwert-Demo","DEMO-IMPORT","DEMO-IMPORT" if status==TaskStatus.RELEASED.value else None)); result_no+=1
    master.update({"samples":pd.DataFrame(sample_rows,columns=["sample_id","batch_id","product_id","sample_type","received_at"]).assign(sample_name=None,notes=None,created_at=lambda frame:frame.received_at,created_by="DEMO-IMPORT"),
                   "tasks":pd.DataFrame(task_rows,columns=["task_id","sample_id","product_id","method_id","received_at","deadline","order_type","priority","status","assignee_id","instrument_id","ordered_at","is_required","system_priority","manual_priority","manual_priority_reason","specification_version","calculation_rule"]),
                   "results":pd.DataFrame(result_rows,columns=["result_id","task_id","parameter","value","unit","target","lsl","usl","quality_status","measured_at","comment","result_version","is_current","validity_status","review_status","released_at","specification_version","calculation_rule","recorded_by","released_by"])})
    completed=master["results"].set_index("task_id")["measured_at"]
    master["tasks"]["completed_at"]=master["tasks"]["task_id"].map(completed).where(master["tasks"]["status"]==TaskStatus.RELEASED.value)
    return master
