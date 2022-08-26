# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\condition_with_args.py
from dataclasses import dataclass
from typing import List
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class ConditionWithArgs(Streamable):
    __doc__ = '\n    This structure is used to store parsed CLVM conditions\n    Conditions in CLVM have either format of (opcode, var1) or (opcode, var1, var2)\n    '
    opcode: ConditionOpcode
    vars: List[bytes]