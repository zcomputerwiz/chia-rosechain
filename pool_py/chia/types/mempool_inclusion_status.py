# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\mempool_inclusion_status.py
from enum import IntEnum

class MempoolInclusionStatus(IntEnum):
    SUCCESS = 1
    PENDING = 2
    FAILED = 3