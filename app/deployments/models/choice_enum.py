from enum import Enum


class ChoiceEnum(Enum):
    """Special Enum that can format it's options for a django choice field"""

    @classmethod
    def choices(cls):
        return tuple((x.name, x.value) for x in cls)
