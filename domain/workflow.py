from domain.enums import ALLOWED_TRANSITIONS, TaskStatus

def validate_transition(current: str, target: str) -> None:
    current_status, target_status = TaskStatus(current), TaskStatus(target)
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"Ungültiger Statusübergang: {current} → {target}")
