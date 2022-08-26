# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\timelord\types.py
from enum import Enum

class Chain(Enum):
    CHALLENGE_CHAIN = 1
    REWARD_CHAIN = 2
    INFUSED_CHALLENGE_CHAIN = 3
    BLUEBOX = 4


class IterationType(Enum):
    SIGNAGE_POINT = 1
    INFUSION_POINT = 2
    END_OF_SUBSLOT = 3


class StateType(Enum):
    PEAK = 1
    END_OF_SUB_SLOT = 2
    FIRST_SUB_SLOT = 3