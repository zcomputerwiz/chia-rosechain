# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\introducer_peers.py
import random, time
from typing import Set, List, Optional
from dataclasses import dataclass
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint64, uint16

@dataclass(frozen=False)
class VettedPeer:
    host: str
    port: uint16
    vetted = 0
    vetted: int
    vetted_timestamp = uint64(0)
    vetted_timestamp: uint64
    last_attempt = uint64(0)
    last_attempt: uint64
    time_added = uint64(0)
    time_added: uint64

    def __init__(self, h: str, p: uint16):
        self.host = h
        self.port = p

    def __eq__(self, rhs):
        return self.host == rhs.host and self.port == rhs.port

    def __hash__(self):
        return hash((self.host, self.port))


class IntroducerPeers:
    __doc__ = '\n    Has the list of known full node peers that are already connected or may be\n    connected to, and the time that they were last added.\n    '

    def __init__(self) -> None:
        self._peers = set()

    def add(self, peer: Optional[PeerInfo]) -> bool:
        if not (peer is None or peer.port):
            return False
        p = VettedPeer(peer.host, peer.port)
        p.time_added = uint64(int(time.time()))
        if p in self._peers:
            return True
        self._peers.add(p)
        return True

    def remove(self, peer: Optional[VettedPeer]) -> bool:
        if not (peer is None or peer.port):
            return False
        try:
            self._peers.remove(peer)
            return True
        except ValueError:
            return False

    def get_peers(self, max_peers: int=0, randomize: bool=False, recent_threshold=9999999) -> List[VettedPeer]:
        target_peers = [peer for peer in self._peers if time.time() - peer.time_added < recent_threshold]
        if not max_peers or max_peers > len(target_peers):
            max_peers = len(target_peers)
        if randomize:
            return random.sample(target_peers, max_peers)
        return target_peers[:max_peers]