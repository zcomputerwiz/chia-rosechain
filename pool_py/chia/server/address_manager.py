# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\server\address_manager.py
import logging, math, time
from asyncio import Lock
from random import choice, randrange
from secrets import randbits
from typing import Dict, List, Optional, Set, Tuple
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint64
TRIED_BUCKETS_PER_GROUP = 8
NEW_BUCKETS_PER_SOURCE_GROUP = 64
TRIED_BUCKET_COUNT = 256
NEW_BUCKET_COUNT = 1024
BUCKET_SIZE = 64
TRIED_COLLISION_SIZE = 10
NEW_BUCKETS_PER_ADDRESS = 8
LOG_TRIED_BUCKET_COUNT = 3
LOG_NEW_BUCKET_COUNT = 10
LOG_BUCKET_SIZE = 6
HORIZON_DAYS = 30
MAX_RETRIES = 3
MIN_FAIL_DAYS = 7
MAX_FAILURES = 10
log = logging.getLogger(__name__)

class ExtendedPeerInfo:

    def __init__(self, addr: TimestampedPeerInfo, src_peer: Optional[PeerInfo]):
        self.peer_info = PeerInfo(addr.host, addr.port)
        self.timestamp = addr.timestamp
        self.src = src_peer
        if src_peer is None:
            self.src = self.peer_info
        self.random_pos = None
        self.is_tried = False
        self.ref_count = 0
        self.last_success = 0
        self.last_try = 0
        self.num_attempts = 0
        self.last_count_attempt = 0

    def to_string(self) -> str:
        assert self.src is not None
        out = self.peer_info.host + ' ' + str(int(self.peer_info.port)) + ' ' + str(int(self.timestamp)) + ' ' + self.src.host + ' ' + str(int(self.src.port))
        return out

    @classmethod
    def from_string(cls, peer_str: str):
        blobs = peer_str.split(' ')
        assert len(blobs) == 5
        peer_info = TimestampedPeerInfo(blobs[0], uint16(int(blobs[1])), uint64(int(blobs[2])))
        src_peer = PeerInfo(blobs[3], uint16(int(blobs[4])))
        return cls(peer_info, src_peer)

    def get_tried_bucket(self, key: int) -> int:
        hash1 = int.from_bytes((bytes(std_hash(key.to_bytes(32, byteorder='big') + self.peer_info.get_key())[:8])),
          byteorder='big')
        hash1 = hash1 % TRIED_BUCKETS_PER_GROUP
        hash2 = int.from_bytes((bytes(std_hash(key.to_bytes(32, byteorder='big') + self.peer_info.get_group() + bytes([hash1]))[:8])),
          byteorder='big')
        return hash2 % TRIED_BUCKET_COUNT

    def get_new_bucket(self, key: int, src_peer: Optional[PeerInfo]=None) -> int:
        if src_peer is None:
            src_peer = self.src
        assert src_peer is not None
        hash1 = int.from_bytes((bytes(std_hash(key.to_bytes(32, byteorder='big') + self.peer_info.get_group() + src_peer.get_group())[:8])),
          byteorder='big')
        hash1 = hash1 % NEW_BUCKETS_PER_SOURCE_GROUP
        hash2 = int.from_bytes((bytes(std_hash(key.to_bytes(32, byteorder='big') + src_peer.get_group() + bytes([hash1]))[:8])),
          byteorder='big')
        return hash2 % NEW_BUCKET_COUNT

    def get_bucket_position(self, key, is_new, nBucket):
        ch = 'N' if is_new else 'K'
        hash1 = int.from_bytes((bytes(std_hash(key.to_bytes(32, byteorder='big') + ch.encode() + nBucket.to_bytes(3, byteorder='big') + self.peer_info.get_key())[:8])),
          byteorder='big')
        return hash1 % BUCKET_SIZE

    def is_terrible(self, now: Optional[int]=None) -> bool:
        if now is None:
            now = int(math.floor(time.time()))
        if self.last_try > 0:
            if self.last_try >= now - 60:
                return False
        if self.timestamp > now + 600:
            return True
        if self.timestamp == 0 or now - self.timestamp > HORIZON_DAYS * 24 * 60 * 60:
            return True
        if self.last_success == 0:
            if self.num_attempts >= MAX_RETRIES:
                return True
        if now - self.last_success > MIN_FAIL_DAYS * 24 * 60 * 60:
            if self.num_attempts >= MAX_FAILURES:
                return True
        return False

    def get_selection_chance(self, now: Optional[int]=None):
        if now is None:
            now = int(math.floor(time.time()))
        chance = 1.0
        since_last_try = max(now - self.last_try, 0)
        if since_last_try < 600:
            chance *= 0.01
        chance *= pow(0.66, min(self.num_attempts, 8))
        return chance


class AddressManager:
    id_count: int
    key: int
    random_pos: List[int]
    tried_matrix: List[List[int]]
    new_matrix: List[List[int]]
    tried_count: int
    new_count: int
    map_addr: Dict[(str, int)]
    map_info: Dict[(int, ExtendedPeerInfo)]
    last_good: int
    tried_collisions: List[int]
    used_new_matrix_positions: Set[Tuple[(int, int)]]
    used_tried_matrix_positions: Set[Tuple[(int, int)]]
    allow_private_subnets: bool

    def __init__(self) -> None:
        self.clear()
        self.lock = Lock()

    def clear(self) -> None:
        self.id_count = 0
        self.key = randbits(256)
        self.random_pos = []
        self.tried_matrix = [[-1 for x in range(BUCKET_SIZE)] for y in range(TRIED_BUCKET_COUNT)]
        self.new_matrix = [[-1 for x in range(BUCKET_SIZE)] for y in range(NEW_BUCKET_COUNT)]
        self.tried_count = 0
        self.new_count = 0
        self.map_addr = {}
        self.map_info = {}
        self.last_good = 1
        self.tried_collisions = []
        self.used_new_matrix_positions = set()
        self.used_tried_matrix_positions = set()
        self.allow_private_subnets = False

    def make_private_subnets_valid(self) -> None:
        self.allow_private_subnets = True

    def _set_new_matrix(self, row, col, value):
        self.new_matrix[row][col] = value
        if value == -1:
            if (
             row, col) in self.used_new_matrix_positions:
                self.used_new_matrix_positions.remove((row, col))
        else:
            if (
             row, col) not in self.used_new_matrix_positions:
                self.used_new_matrix_positions.add((row, col))

    def _set_tried_matrix(self, row, col, value):
        self.tried_matrix[row][col] = value
        if value == -1:
            if (
             row, col) in self.used_tried_matrix_positions:
                self.used_tried_matrix_positions.remove((row, col))
        else:
            if (
             row, col) not in self.used_tried_matrix_positions:
                self.used_tried_matrix_positions.add((row, col))

    def load_used_table_positions(self) -> None:
        self.used_new_matrix_positions = set()
        self.used_tried_matrix_positions = set()
        for bucket in range(NEW_BUCKET_COUNT):
            for pos in range(BUCKET_SIZE):
                if self.new_matrix[bucket][pos] != -1:
                    self.used_new_matrix_positions.add((bucket, pos))

        for bucket in range(TRIED_BUCKET_COUNT):
            for pos in range(BUCKET_SIZE):
                if self.tried_matrix[bucket][pos] != -1:
                    self.used_tried_matrix_positions.add((bucket, pos))

    def create_(self, addr: TimestampedPeerInfo, addr_src: Optional[PeerInfo]) -> Tuple[(ExtendedPeerInfo, int)]:
        self.id_count += 1
        node_id = self.id_count
        self.map_info[node_id] = ExtendedPeerInfo(addr, addr_src)
        self.map_addr[addr.host] = node_id
        self.map_info[node_id].random_pos = len(self.random_pos)
        self.random_pos.append(node_id)
        return (
         self.map_info[node_id], node_id)

    def find_(self, addr: PeerInfo) -> Tuple[(Optional[ExtendedPeerInfo], Optional[int])]:
        if addr.host not in self.map_addr:
            return (None, None)
        node_id = self.map_addr[addr.host]
        if node_id not in self.map_info:
            return (None, node_id)
        return (self.map_info[node_id], node_id)

    def swap_random_(self, rand_pos_1: int, rand_pos_2: int) -> None:
        if rand_pos_1 == rand_pos_2:
            return
        if not (rand_pos_1 < len(self.random_pos) and rand_pos_2 < len(self.random_pos)):
            raise AssertionError
        node_id_1 = self.random_pos[rand_pos_1]
        node_id_2 = self.random_pos[rand_pos_2]
        self.map_info[node_id_1].random_pos = rand_pos_2
        self.map_info[node_id_2].random_pos = rand_pos_1
        self.random_pos[rand_pos_1] = node_id_2
        self.random_pos[rand_pos_2] = node_id_1

    def make_tried_(self, info: ExtendedPeerInfo, node_id: int) -> None:
        for bucket in range(NEW_BUCKET_COUNT):
            pos = info.get_bucket_position(self.key, True, bucket)
            if self.new_matrix[bucket][pos] == node_id:
                self._set_new_matrix(bucket, pos, -1)
                info.ref_count -= 1

        assert info.ref_count == 0
        self.new_count -= 1
        cur_bucket = info.get_tried_bucket(self.key)
        cur_bucket_pos = info.get_bucket_position(self.key, False, cur_bucket)
        if self.tried_matrix[cur_bucket][cur_bucket_pos] != -1:
            node_id_evict = self.tried_matrix[cur_bucket][cur_bucket_pos]
            assert node_id_evict in self.map_info
            old_info = self.map_info[node_id_evict]
            old_info.is_tried = False
            self._set_tried_matrix(cur_bucket, cur_bucket_pos, -1)
            self.tried_count -= 1
            new_bucket = old_info.get_new_bucket(self.key)
            new_bucket_pos = old_info.get_bucket_position(self.key, True, new_bucket)
            self.clear_new_(new_bucket, new_bucket_pos)
            old_info.ref_count = 1
            self._set_new_matrix(new_bucket, new_bucket_pos, node_id_evict)
            self.new_count += 1
        self._set_tried_matrix(cur_bucket, cur_bucket_pos, node_id)
        self.tried_count += 1
        info.is_tried = True

    def clear_new_(self, bucket: int, pos: int) -> None:
        if self.new_matrix[bucket][pos] != -1:
            delete_id = self.new_matrix[bucket][pos]
            delete_info = self.map_info[delete_id]
            assert delete_info.ref_count > 0
            delete_info.ref_count -= 1
            self._set_new_matrix(bucket, pos, -1)
            if delete_info.ref_count == 0:
                self.delete_new_entry_(delete_id)

    def mark_good_(self, addr, test_before_evict, timestamp):
        self.last_good = timestamp
        info, node_id = self.find_(addr)
        if not addr.is_valid(self.allow_private_subnets):
            return
        if info is None:
            return
        if node_id is None:
            return
        if not (info.peer_info.host == addr.host and info.peer_info.port == addr.port):
            return
        info.last_success = timestamp
        info.last_try = timestamp
        info.num_attempts = 0
        if info.is_tried:
            return
        bucket_rand = randrange(NEW_BUCKET_COUNT)
        new_bucket = -1
        for n in range(NEW_BUCKET_COUNT):
            cur_new_bucket = (n + bucket_rand) % NEW_BUCKET_COUNT
            cur_new_bucket_pos = info.get_bucket_position(self.key, True, cur_new_bucket)
            if self.new_matrix[cur_new_bucket][cur_new_bucket_pos] == node_id:
                new_bucket = cur_new_bucket
                break

        if new_bucket == -1:
            return
        tried_bucket = info.get_tried_bucket(self.key)
        tried_bucket_pos = info.get_bucket_position(self.key, False, tried_bucket)
        if test_before_evict and self.tried_matrix[tried_bucket][tried_bucket_pos] != -1:
            if not len(self.tried_collisions) < TRIED_COLLISION_SIZE or node_id not in self.tried_collisions:
                self.tried_collisions.append(node_id)
        else:
            self.make_tried_(info, node_id)

    def delete_new_entry_(self, node_id: int) -> None:
        info = self.map_info[node_id]
        if info is None or info.random_pos is None:
            return
        self.swap_random_(info.random_pos, len(self.random_pos) - 1)
        self.random_pos = self.random_pos[:-1]
        del self.map_addr[info.peer_info.host]
        del self.map_info[node_id]
        self.new_count -= 1

    def add_to_new_table_(self, addr: TimestampedPeerInfo, source: Optional[PeerInfo], penalty: int) -> bool:
        is_unique = False
        peer_info = PeerInfo(addr.host, addr.port)
        if not peer_info.is_valid(self.allow_private_subnets):
            return False
        info, node_id = self.find_(peer_info)
        if info is not None:
            if info.peer_info.host == addr.host:
                if info.peer_info.port == addr.port:
                    penalty = 0
        if info is not None:
            currently_online = time.time() - addr.timestamp < 86400
            update_interval = 3600 if currently_online else 86400
            if addr.timestamp > 0:
                if info.timestamp > 0 or info.timestamp < addr.timestamp - update_interval - penalty:
                    info.timestamp = max(0, addr.timestamp - penalty)
                if addr.timestamp == 0 or info.timestamp > 0 and addr.timestamp <= info.timestamp:
                    return False
                if info.is_tried:
                    return False
                if info.ref_count == NEW_BUCKETS_PER_ADDRESS:
                    return False
            factor = 1 << info.ref_count
            if factor > 1:
                if randrange(factor) != 0:
                    return False
        else:
            info, node_id = self.create_(addr, source)
            info.timestamp = max(0, info.timestamp - penalty)
            self.new_count += 1
            is_unique = True
        new_bucket = info.get_new_bucket(self.key, source)
        new_bucket_pos = info.get_bucket_position(self.key, True, new_bucket)
        if self.new_matrix[new_bucket][new_bucket_pos] != node_id:
            add_to_new = self.new_matrix[new_bucket][new_bucket_pos] == -1
            info_existing = (add_to_new or self.map_info)[self.new_matrix[new_bucket][new_bucket_pos]]
            if info_existing.is_terrible() or info_existing.ref_count > 1 and info.ref_count == 0:
                add_to_new = True
            if add_to_new:
                self.clear_new_(new_bucket, new_bucket_pos)
                info.ref_count += 1
                if node_id is not None:
                    self._set_new_matrix(new_bucket, new_bucket_pos, node_id)
            else:
                if info.ref_count == 0:
                    if node_id is not None:
                        self.delete_new_entry_(node_id)
        return is_unique

    def attempt_(self, addr, count_failures, timestamp):
        info, _ = self.find_(addr)
        if info is None:
            return
        if not (info.peer_info.host == addr.host and info.peer_info.port == addr.port):
            return
        info.last_try = timestamp
        if count_failures:
            if info.last_count_attempt < self.last_good:
                info.last_count_attempt = timestamp
                info.num_attempts += 1

    def select_peer_(self, new_only: bool) -> Optional[ExtendedPeerInfo]:
        if len(self.random_pos) == 0:
            return
        if new_only:
            if self.new_count == 0:
                return
        if (new_only or self.tried_count) > 0 and self.new_count == 0 or randrange(2) == 0:
            chance = 1.0
            start = time.time()
            cached_tried_matrix_positions = []
            if len(self.used_tried_matrix_positions) < math.sqrt(TRIED_BUCKET_COUNT * BUCKET_SIZE):
                cached_tried_matrix_positions = list(self.used_tried_matrix_positions)
            while True:
                if len(self.used_tried_matrix_positions) < math.sqrt(TRIED_BUCKET_COUNT * BUCKET_SIZE):
                    if len(self.used_tried_matrix_positions) == 0:
                        log.error(f"Empty tried table, but tried_count shows {self.tried_count}.")
                        return
                    index = randrange(len(cached_tried_matrix_positions))
                    tried_bucket, tried_bucket_pos = cached_tried_matrix_positions[index]
                else:
                    tried_bucket = randrange(TRIED_BUCKET_COUNT)
                    tried_bucket_pos = randrange(BUCKET_SIZE)
                    while self.tried_matrix[tried_bucket][tried_bucket_pos] == -1:
                        tried_bucket = (tried_bucket + randbits(LOG_TRIED_BUCKET_COUNT)) % TRIED_BUCKET_COUNT
                        tried_bucket_pos = (tried_bucket_pos + randbits(LOG_BUCKET_SIZE)) % BUCKET_SIZE

                node_id = self.tried_matrix[tried_bucket][tried_bucket_pos]
                if not node_id != -1:
                    raise AssertionError
                else:
                    info = self.map_info[node_id]
                    if randbits(30) < chance * info.get_selection_chance() * 1073741824:
                        end = time.time()
                        log.debug(f"address_manager.select_peer took {end - start:.2e} seconds in tried table.")
                        return info
                    chance *= 1.2

        else:
            chance = 1.0
            start = time.time()
            cached_new_matrix_positions = []
            if len(self.used_new_matrix_positions) < math.sqrt(NEW_BUCKET_COUNT * BUCKET_SIZE):
                cached_new_matrix_positions = list(self.used_new_matrix_positions)
            while True:
                if len(self.used_new_matrix_positions) < math.sqrt(NEW_BUCKET_COUNT * BUCKET_SIZE):
                    if len(self.used_new_matrix_positions) == 0:
                        log.error(f"Empty new table, but new_count shows {self.new_count}.")
                        return
                    index = randrange(len(cached_new_matrix_positions))
                    new_bucket, new_bucket_pos = cached_new_matrix_positions[index]
                else:
                    new_bucket = randrange(NEW_BUCKET_COUNT)
                    new_bucket_pos = randrange(BUCKET_SIZE)
                    while self.new_matrix[new_bucket][new_bucket_pos] == -1:
                        new_bucket = (new_bucket + randbits(LOG_NEW_BUCKET_COUNT)) % NEW_BUCKET_COUNT
                        new_bucket_pos = (new_bucket_pos + randbits(LOG_BUCKET_SIZE)) % BUCKET_SIZE

                node_id = self.new_matrix[new_bucket][new_bucket_pos]
                if not node_id != -1:
                    raise AssertionError
                else:
                    info = self.map_info[node_id]
                    if randbits(30) < chance * info.get_selection_chance() * 1073741824:
                        end = time.time()
                        log.debug(f"address_manager.select_peer took {end - start:.2e} seconds in new table.")
                        return info
                    chance *= 1.2

    def resolve_tried_collisions_(self) -> None:
        for node_id in self.tried_collisions[:]:
            resolved = False
            if node_id not in self.map_info:
                resolved = True
            else:
                info = self.map_info[node_id]
                peer = info.peer_info
                tried_bucket = info.get_tried_bucket(self.key)
                tried_bucket_pos = info.get_bucket_position(self.key, False, tried_bucket)
                if self.tried_matrix[tried_bucket][tried_bucket_pos] != -1:
                    old_id = self.tried_matrix[tried_bucket][tried_bucket_pos]
                    old_info = self.map_info[old_id]
                    if time.time() - old_info.last_success < 14400:
                        resolved = True
                    else:
                        if time.time() - old_info.last_try < 14400:
                            if time.time() - old_info.last_try > 60:
                                self.mark_good_(peer, False, math.floor(time.time()))
                                resolved = True
                        else:
                            if time.time() - info.last_success > 2400:
                                self.mark_good_(peer, False, math.floor(time.time()))
                                resolved = True
                else:
                    self.mark_good_(peer, False, math.floor(time.time()))
                    resolved = True
            if resolved:
                self.tried_collisions.remove(node_id)

    def select_tried_collision_(self) -> Optional[ExtendedPeerInfo]:
        if len(self.tried_collisions) == 0:
            return
        new_id = choice(self.tried_collisions)
        if new_id not in self.map_info:
            self.tried_collisions.remove(new_id)
            return
        new_info = self.map_info[new_id]
        tried_bucket = new_info.get_tried_bucket(self.key)
        tried_bucket_pos = new_info.get_bucket_position(self.key, False, tried_bucket)
        old_id = self.tried_matrix[tried_bucket][tried_bucket_pos]
        return self.map_info[old_id]

    def get_peers_(self) -> List[TimestampedPeerInfo]:
        addr = []
        num_nodes = math.ceil(23 * len(self.random_pos) / 100)
        if num_nodes > 1000:
            num_nodes = 1000
        for n in range(len(self.random_pos)):
            if len(addr) >= num_nodes:
                return addr
            else:
                rand_pos = randrange(len(self.random_pos) - n) + n
                self.swap_random_(n, rand_pos)
                info = self.map_info[self.random_pos[n]]
            if not info.peer_info.is_valid(self.allow_private_subnets):
                continue
            if not info.is_terrible():
                cur_peer_info = TimestampedPeerInfo(info.peer_info.host, uint16(info.peer_info.port), uint64(info.timestamp))
                addr.append(cur_peer_info)

        return addr

    def cleanup(self, max_timestamp_difference: int, max_consecutive_failures: int):
        now = int(math.floor(time.time()))
        for bucket in range(NEW_BUCKET_COUNT):
            for pos in range(BUCKET_SIZE):
                if self.new_matrix[bucket][pos] != -1:
                    node_id = self.new_matrix[bucket][pos]
                    cur_info = self.map_info[node_id]
                    if cur_info.timestamp < now - max_timestamp_difference:
                        if cur_info.num_attempts >= max_consecutive_failures:
                            self.clear_new_(bucket, pos)

    def connect_(self, addr: PeerInfo, timestamp: int):
        info, _ = self.find_(addr)
        if info is None:
            return
        if not (info.peer_info.host == addr.host and info.peer_info.port == addr.port):
            return
        update_interval = 1200
        if timestamp - info.timestamp > update_interval:
            info.timestamp = timestamp

    async def size(self) -> int:
        async with self.lock:
            return len(self.random_pos)

    async def add_to_new_table(self, addresses: List[TimestampedPeerInfo], source: Optional[PeerInfo]=None, penalty: int=0) -> bool:
        is_added = False
        async with self.lock:
            for addr in addresses:
                cur_peer_added = self.add_to_new_table_(addr, source, penalty)
                is_added = is_added or cur_peer_added

        return is_added

    async def mark_good(self, addr: PeerInfo, test_before_evict: bool=True, timestamp: int=-1):
        if timestamp == -1:
            timestamp = math.floor(time.time())
        async with self.lock:
            self.mark_good_(addr, test_before_evict, timestamp)

    async def attempt(self, addr: PeerInfo, count_failures: bool, timestamp: int=-1):
        if timestamp == -1:
            timestamp = math.floor(time.time())
        async with self.lock:
            self.attempt_(addr, count_failures, timestamp)

    async def resolve_tried_collisions(self):
        async with self.lock:
            self.resolve_tried_collisions_()

    async def select_tried_collision(self) -> Optional[ExtendedPeerInfo]:
        async with self.lock:
            return self.select_tried_collision_()

    async def select_peer(self, new_only: bool=False) -> Optional[ExtendedPeerInfo]:
        async with self.lock:
            return self.select_peer_(new_only)

    async def get_peers(self) -> List[TimestampedPeerInfo]:
        async with self.lock:
            return self.get_peers_()

    async def connect(self, addr: PeerInfo, timestamp: int=-1):
        if timestamp == -1:
            timestamp = math.floor(time.time())
        async with self.lock:
            return self.connect_(addr, timestamp)