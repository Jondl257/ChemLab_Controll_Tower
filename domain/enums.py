from enum import StrEnum

class TaskStatus(StrEnum):
    OPEN = "Offen"
    CLAIMED = "Übernommen"
    IN_PROGRESS = "In Bearbeitung"
    RESULT_RECORDED = "Ergebnis erfasst"
    REVIEW_REQUIRED = "Prüfung erforderlich"
    RELEASED = "Freigegeben"
    CANCELLED = "Abgebrochen"

class ResultStatus(StrEnum):
    PASS = "PASS"
    NEAR_LIMIT = "GRENZNAH"
    OOS = "OOS"

ALLOWED_TRANSITIONS = {
    TaskStatus.OPEN: {TaskStatus.CLAIMED, TaskStatus.CANCELLED},
    TaskStatus.CLAIMED: {TaskStatus.IN_PROGRESS, TaskStatus.OPEN, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.RESULT_RECORDED, TaskStatus.CANCELLED},
    TaskStatus.RESULT_RECORDED: {TaskStatus.REVIEW_REQUIRED},
    TaskStatus.REVIEW_REQUIRED: {TaskStatus.RELEASED, TaskStatus.IN_PROGRESS},
    TaskStatus.RELEASED: set(), TaskStatus.CANCELLED: set(),
}
