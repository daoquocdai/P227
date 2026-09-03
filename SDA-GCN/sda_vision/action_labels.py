"""Authoritative labels for the deployed five-class SDA-GCN checkpoint.

The class order is the one used by the repository's trained-checkpoint
inference path: Fall, Dung, Cui, Ngoi, Nam.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActionClass:
    class_id: int
    name: str
    label: str


ACTION_CLASSES = {
    0: ActionClass(0, "fall", "Ngã"),
    1: ActionClass(1, "standing", "Đứng"),
    2: ActionClass(2, "bending", "Cúi"),
    3: ActionClass(3, "sitting", "Ngồi"),
    4: ActionClass(4, "lying", "Nằm"),
}


def action_class(class_id: int) -> ActionClass | None:
    return ACTION_CLASSES.get(class_id)
