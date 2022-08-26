# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\classgroup.py
from dataclasses import dataclass
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes100
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    __doc__ = '\n    Represents a classgroup element (a,b,c) where a, b, and c are 512 bit signed integers. However this is using\n    a compressed representation. VDF outputs are a single classgroup element. VDF proofs can also be one classgroup\n    element (or multiple).\n    '
    data: bytes100

    @staticmethod
    def from_bytes(data) -> 'ClassgroupElement':
        if len(data) < 100:
            data += b'\x00' * (100 - len(data))
        return ClassgroupElement(bytes100(data))

    @staticmethod
    def get_default_element() -> 'ClassgroupElement':
        return ClassgroupElement.from_bytes(b'\x08')

    @staticmethod
    def get_size(constants: ConsensusConstants):
        return 100