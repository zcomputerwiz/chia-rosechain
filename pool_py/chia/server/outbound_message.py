# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\outbound_message.py
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.ints import uint8, uint16
from chia.util.streamable import Streamable, streamable

class NodeType(IntEnum):
    FULL_NODE = 1
    HARVESTER = 2
    FARMER = 3
    TIMELORD = 4
    INTRODUCER = 5
    WALLET = 6


class Delivery(IntEnum):
    RESPOND = 1
    BROADCAST = 2
    BROADCAST_TO_OTHERS = 3
    RANDOM = 4
    CLOSE = 5
    SPECIFIC = 6


@dataclass(frozen=True)
@streamable
class Message(Streamable):
    type: uint8
    id: Optional[uint16]
    data: bytes


def make_msg(msg_type: ProtocolMessageTypes, data: Any) -> Message:
    return Message(uint8(msg_type.value), None, bytes(data))