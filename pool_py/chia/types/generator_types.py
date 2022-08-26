# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\generator_types.py
from dataclasses import dataclass
from typing import List
from chia.types.blockchain_format.program import SerializedProgram
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable

class GeneratorBlockCacheInterface:

    def get_generator_for_block_height(self, height: uint32) -> SerializedProgram:
        pass


@dataclass(frozen=True)
@streamable
class GeneratorArg(Streamable):
    __doc__ = '`GeneratorArg` contains data from already-buried blocks in the blockchain'
    block_height: uint32
    generator: SerializedProgram


@dataclass(frozen=True)
class CompressorArg:
    __doc__ = '`CompressorArg` is used as input to the Block Compressor'
    block_height: uint32
    generator: SerializedProgram
    start: int
    end: int


@dataclass(frozen=True)
@streamable
class BlockGenerator(Streamable):
    program: SerializedProgram
    generator_args: List[GeneratorArg]

    def block_height_list(self) -> List[uint32]:
        return [a.block_height for a in self.generator_args]

    def generator_refs(self) -> List[SerializedProgram]:
        return [a.generator for a in self.generator_args]