# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\wallet_action_store.py
from typing import List, Optional
import aiosqlite
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction

class WalletActionStore:
    __doc__ = '\n    WalletActionStore keeps track of all wallet actions that require persistence.\n    Used by Colored coins, Atomic swaps, Rate Limited, and Authorized payee wallets\n    '
    db_connection: aiosqlite.Connection
    cache_size: uint32
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()
        self.db_wrapper = db_wrapper
        self.db_connection = db_wrapper.db
        await self.db_connection.execute('CREATE TABLE IF NOT EXISTS action_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, name text, wallet_id int, wallet_type int, wallet_callback text, done int, data text)')
        await self.db_connection.execute('CREATE INDEX IF NOT EXISTS name on action_queue(name)')
        await self.db_connection.execute('CREATE INDEX IF NOT EXISTS wallet_id on action_queue(wallet_id)')
        await self.db_connection.execute('CREATE INDEX IF NOT EXISTS wallet_type on action_queue(wallet_type)')
        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute('DELETE FROM action_queue')
        await cursor.close()
        await self.db_connection.commit()

    async def get_wallet_action(self, id: int) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """
        cursor = await self.db_connection.execute('SELECT * from action_queue WHERE id=?', (id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return
        return WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])

    async def create_action(self, name, wallet_id, type, callback, done, data, in_transaction):
        """
        Creates Wallet Action
        """
        if not in_transaction:
            await self.db_wrapper.lock.acquire()
        try:
            cursor = await self.db_connection.execute('INSERT INTO action_queue VALUES(?, ?, ?, ?, ?, ?, ?)', (
             None, name, wallet_id, type, callback, done, data))
            await cursor.close()
        finally:
            if not in_transaction:
                await self.db_connection.commit()
                self.db_wrapper.lock.release()

    async def action_done(self, action_id: int):
        """
        Marks action as done
        """
        action = await self.get_wallet_action(action_id)
        assert action is not None
        async with self.db_wrapper.lock:
            cursor = await self.db_connection.execute('Replace INTO action_queue VALUES(?, ?, ?, ?, ?, ?, ?)', (
             action.id,
             action.name,
             action.wallet_id,
             action.type.value,
             action.wallet_callback,
             True,
             action.data))
            await cursor.close()
            await self.db_connection.commit()

    async def get_all_pending_actions(self) -> List[WalletAction]:
        """
        Returns list of all pending action
        """
        result = []
        cursor = await self.db_connection.execute('SELECT * from action_queue WHERE done=?', (0, ))
        rows = await cursor.fetchall()
        await cursor.close()
        if rows is None:
            return result
        for row in rows:
            action = WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])
            result.append(action)

        return result

    async def get_action_by_id(self, id) -> Optional[WalletAction]:
        """
        Return a wallet action by id
        """
        cursor = await self.db_connection.execute('SELECT * from action_queue WHERE id=?', (id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return
        return WalletAction(row[0], row[1], row[2], WalletType(row[3]), row[4], bool(row[5]), row[6])