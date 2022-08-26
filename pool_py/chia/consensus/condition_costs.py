# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\condition_costs.py
from enum import Enum

class ConditionCost(Enum):
    AGG_SIG = 1200
    CREATE_COIN = 1800
    ASSERT_MY_COIN_ID = 0
    ASSERT_MY_PARENT_ID = 0
    ASSERT_MY_PUZZLEHASH = 0
    ASSERT_MY_AMOUNT = 0
    ASSERT_SECONDS_RELATIVE = 0
    ASSERT_SECONDS_ABSOLUTE = 0
    ASSERT_HEIGHT_RELATIVE = 0
    ASSERT_HEIGHT_ABSOLUTE = 0
    RESERVE_FEE = 0
    CREATE_COIN_ANNOUNCEMENT = 0
    ASSERT_COIN_ANNOUNCEMENT = 0
    CREATE_PUZZLE_ANNOUNCEMENT = 0
    ASSERT_PUZZLE_ANNOUNCEMENT = 0