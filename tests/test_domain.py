import pandas as pd
import pytest
from data.generator import generate_demo_data
from domain.quality import assess
from domain.statistics import process_statistics
from domain.workflow import validate_transition

def test_generator_references_are_valid():
    d=generate_demo_data(); assert set(d["tasks"].sample_id).issubset(set(d["samples"].sample_id)); assert set(d["results"].task_id).issubset(set(d["tasks"].task_id))
def test_oos_logic():
    assert assess(0.9,1,2)=="OOS"; assert assess(2.1,1,2)=="OOS"; assert assess(1.5,1,2)=="PASS"
def test_statistics_known_values():
    s=process_statistics(pd.Series([1.,2.,3.]),0.,4.); assert s["mean"]==2 and s["cp"] is not None
def test_invalid_transition_is_blocked():
    with pytest.raises(ValueError): validate_transition("Offen","Freigegeben")
