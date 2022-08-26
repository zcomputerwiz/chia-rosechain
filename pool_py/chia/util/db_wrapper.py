# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\db_wrapper.py
import asyncio, aiosqlite

class DBWrapper:
    __doc__ = '\n    This object handles HeaderBlocks and Blocks stored in DB used by wallet.\n    '
    db: aiosqlite.Connection
    lock: asyncio.Lock

    def __init__(self, connection: aiosqlite.Connection):
        self.db = connection
        self.lock = asyncio.Lock()

    async def begin_transaction(self):
        cursor = await self.db.execute('BEGIN TRANSACTION')
        await cursor.close()

    async def rollback_transaction(self):
        if self.db.in_transaction:
            cursor = await self.db.execute('ROLLBACK')
            await cursor.close()

    async def commit_transaction(self):
        await self.db.commit()