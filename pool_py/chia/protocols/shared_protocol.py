# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\protocols\shared_protocol.py
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Tuple
from chia.util.ints import uint8, uint16
from chia.util.streamable import Streamable, streamable
protocol_version = '0.0.32'

class Capability(IntEnum):
    BASE = 1


@dataclass(frozen=True)
@streamable
class Handshake(Streamable):
    network_id: str
    protocol_version: str
    software_version: str
    server_port: uint16
    node_type: uint8
    capabilities: List[Tuple[(uint16, str)]]