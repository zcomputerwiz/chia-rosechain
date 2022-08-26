# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\protocols\introducer_protocol.py
from dataclasses import dataclass
from typing import List
from chia.types.peer_info import TimestampedPeerInfo
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class RequestPeersIntroducer(Streamable):
    __doc__ = '\n    Return full list of peers\n    '


@dataclass(frozen=True)
@streamable
class RespondPeersIntroducer(Streamable):
    peer_list: List[TimestampedPeerInfo]