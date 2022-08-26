# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_sync_store.py
import asyncio, logging
from typing import Dict, List, Optional, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32
log = logging.getLogger(__name__)

class WalletSyncStore:
    sync_mode: bool
    waiting_for_peaks: bool
    potential_peaks: Dict[(bytes32, HeaderBlock)]
    potential_blocks: Dict[(uint32, HeaderBlock)]
    potential_blocks_received: Dict[(uint32, asyncio.Event)]
    potential_future_blocks: List[HeaderBlock]
    header_hashes_added: Dict[(uint32, bytes32)]
    peak_fork_point: Dict[(bytes32, uint32)]

    @classmethod
    async def create(cls) -> 'WalletSyncStore':
        self = cls()
        self.sync_mode = False
        self.waiting_for_peaks = True
        self.potential_peaks = {}
        self.potential_blocks = {}
        self.potential_blocks_received = {}
        self.potential_future_blocks = []
        self.header_hashes_added = {}
        self.peak_fork_point = {}
        return self

    def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    async def clear_sync_info(self):
        self.potential_peaks.clear()
        self.potential_blocks.clear()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()
        self.header_hashes_added.clear()
        self.waiting_for_peaks = True
        self.peak_fork_point = {}

    def get_potential_peaks_tuples(self) -> List[Tuple[(bytes32, HeaderBlock)]]:
        return list(self.potential_peaks.items())

    def add_potential_peak(self, block: HeaderBlock) -> None:
        self.potential_peaks[block.header_hash] = block

    def add_potential_fork_point(self, peak_hash: bytes32, fork_point: uint32):
        self.peak_fork_point[peak_hash] = fork_point

    def get_potential_fork_point(self, peak_hash) -> Optional[uint32]:
        if peak_hash in self.peak_fork_point:
            return self.peak_fork_point[peak_hash]
        return

    def get_potential_peak(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        return self.potential_peaks.get(header_hash, None)

    def add_potential_future_block(self, block: HeaderBlock):
        self.potential_future_blocks.append(block)

    def get_potential_future_blocks(self):
        return self.potential_future_blocks

    def add_header_hashes_added(self, height: uint32, header_hash: bytes32):
        self.header_hashes_added[height] = header_hash

    def get_header_hashes_added(self, height: uint32) -> Optional[bytes32]:
        return self.header_hashes_added.get(height, None)