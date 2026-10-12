"""Central specification assessment. Not a real QC release rule."""
from config import NEAR_LIMIT_FRACTION
from domain.enums import ResultStatus

def assess(value: float, lsl: float | None, usl: float | None) -> str:
    if lsl is not None and value < lsl or usl is not None and value > usl:
        return ResultStatus.OOS.value
    if lsl is not None and usl is not None:
        width = usl - lsl
        if value <= lsl + width * NEAR_LIMIT_FRACTION or value >= usl - width * NEAR_LIMIT_FRACTION:
            return ResultStatus.NEAR_LIMIT.value
    return ResultStatus.PASS.value
