# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\name_puzzle_condition.py
from dataclasses import dataclass
from typing import Dict, List, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.condition_tools import ConditionOpcode
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class NPC(Streamable):
    coin_name: bytes32
    puzzle_hash: bytes32
    conditions: List[Tuple[(ConditionOpcode, List[ConditionWithArgs])]]

    @property
    def condition_dict(self):
        d = {}
        for opcode, l in self.conditions:
            d[opcode] = l

        return d