# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\coin_spend.py
from dataclasses import dataclass
from typing import List
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram, INFINITE_COST
from chia.util.chain_utils import additions_for_solution
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class CoinSpend(Streamable):
    __doc__ = "\n    This is a rather disparate data structure that validates coin transfers. It's generally populated\n    with data from different sources, since burned coins are identified by name, so it is built up\n    more often that it is streamed.\n    "
    coin: Coin
    puzzle_reveal: SerializedProgram
    solution: SerializedProgram

    def additions(self) -> List[Coin]:
        return additions_for_solution(self.coin.name(), self.puzzle_reveal, self.solution, INFINITE_COST)