# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_interested_store.py
from typing import List, Tuple, Optional
import aiosqlite
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper

class WalletInterestedStore:
    __doc__ = '\n    Stores coin ids that we are interested in receiving\n    '
    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, wrapper: DBWrapper):
        self = cls()
        self.db_connection = wrapper.db
        self.db_wrapper = wrapper
        await self.db_connection.execute('pragma journal_mode=wal')
        await self.db_connection.execute('pragma synchronous=2')
        await self.db_connection.execute('CREATE TABLE IF NOT EXISTS interested_coins(coin_name text PRIMARY KEY)')
        await self.db_connection.execute('CREATE TABLE IF NOT EXISTS interested_puzzle_hashes(puzzle_hash text PRIMARY KEY, wallet_id integer)')
        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute('DELETE FROM puzzle_hashes')
        await cursor.close()
        cursor = await self.db_connection.execute('DELETE FROM interested_coins')
        await cursor.close()
        await self.db_connection.commit()

    async def get_interested_coin_ids(self) -> List[bytes32]:
        cursor = await self.db_connection.execute('SELECT coin_name FROM interested_coins')
        rows_hex = await cursor.fetchall()
        return [bytes32(bytes.fromhex(row[0])) for row in rows_hex]

    async def add_interested_coin_id(self, coin_id: bytes32, in_transaction: bool=False) -> None:
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute('INSERT OR REPLACE INTO interested_coins VALUES (?)', (coin_id.hex(),))
            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def get_interested_puzzle_hashes(self) -> List[Tuple[(bytes32, int)]]:
        cursor = await self.db_connection.execute('SELECT puzzle_hash, wallet_id FROM interested_puzzle_hashes')
        rows_hex = await cursor.fetchall()
        return [(bytes32(bytes.fromhex(row[0])), row[1]) for row in rows_hex]

    async def get_interested_puzzle_hash_wallet_id(self, puzzle_hash: bytes32) -> Optional[int]:
        cursor = await self.db_connection.execute('SELECT wallet_id FROM interested_puzzle_hashes WHERE puzzle_hash=?', (puzzle_hash.hex(),))
        row = await cursor.fetchone()
        if row is None:
            return
        return row[0]

    async def add_interested_puzzle_hash(self, puzzle_hash, wallet_id, in_transaction=False):
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute('INSERT OR REPLACE INTO interested_puzzle_hashes VALUES (?, ?)', (puzzle_hash.hex(), wallet_id))
            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def remove_interested_puzzle_hash(self, puzzle_hash: bytes32, in_transaction: bool=False) -> None:
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute('DELETE FROM interested_puzzle_hashes WHERE puzzle_hash=?', (puzzle_hash.hex(),))
            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()