# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\types\blockchain_format\vdf.py
import logging, traceback
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional
from functools import lru_cache
from chiavdf import create_discriminant, verify_n_wesolowski
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable
log = logging.getLogger(__name__)

@lru_cache(maxsize=200)
def get_discriminant(challenge, size_bites) -> int:
    return int(create_discriminant(challenge, size_bites), 16)


@lru_cache(maxsize=1000)
def verify_vdf(disc, input_el, output, number_of_iterations, discriminant_size, witness_type):
    return verify_n_wesolowski(str(disc), input_el, output, number_of_iterations, discriminant_size, witness_type)


@dataclass(frozen=True)
@streamable
class VDFInfo(Streamable):
    challenge: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement


@dataclass(frozen=True)
@streamable
class VDFProof(Streamable):
    witness_type: uint8
    witness: bytes
    normalized_to_identity: bool

    def is_valid(self, constants: ConsensusConstants, input_el: ClassgroupElement, info: VDFInfo, target_vdf_info: Optional[VDFInfo]=None) -> bool:
        """
        If target_vdf_info is passed in, it is compared with info.
        """
        if target_vdf_info is not None:
            if info != target_vdf_info:
                tb = traceback.format_stack()
                log.error(f"{tb} INVALID VDF INFO. Have: {info} Expected: {target_vdf_info}")
                return False
        if self.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
            return False
        try:
            disc = get_discriminant(info.challenge, constants.DISCRIMINANT_SIZE_BITS)
            return verify_vdf(disc, input_el.data, info.output.data + bytes(self.witness), info.number_of_iterations, constants.DISCRIMINANT_SIZE_BITS, self.witness_type)
        except Exception:
            return False


class CompressibleVDFField(IntEnum):
    CC_EOS_VDF = 1
    ICC_EOS_VDF = 2
    CC_SP_VDF = 3
    CC_IP_VDF = 4