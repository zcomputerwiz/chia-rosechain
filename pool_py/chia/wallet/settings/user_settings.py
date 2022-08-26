# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\settings\user_settings.py
from typing import Any, Dict
from chia.wallet.key_val_store import KeyValStore
import chia.wallet.settings.default_settings as default_settings
from chia.wallet.settings.settings_objects import BackupInitialized

class UserSettings:
    settings: Dict[(str, Any)]
    basic_store: KeyValStore

    @staticmethod
    async def create(store: KeyValStore, name: str=None):
        self = UserSettings()
        self.basic_store = store
        self.settings = {}
        await self.load_store()
        return self

    def _keys(self):
        all_keys = [
         BackupInitialized]
        return all_keys

    async def load_store(self):
        keys = self._keys()
        for setting in keys:
            name = setting.__name__
            object = await self.basic_store.get_object(name, BackupInitialized)
            if object is None:
                object = default_settings[name]
            else:
                assert object is not None
                self.settings[name] = object

    async def setting_updated(self, setting: Any):
        name = setting.__class__.__name__
        await self.basic_store.set_object(name, setting)
        self.settings[name] = setting

    async def user_skipped_backup_import(self):
        new = BackupInitialized(user_initialized=True,
          user_skipped=True,
          backup_info_imported=False,
          new_wallet=False)
        await self.setting_updated(new)
        return new

    async def user_imported_backup(self):
        new = BackupInitialized(user_initialized=True,
          user_skipped=False,
          backup_info_imported=True,
          new_wallet=False)
        await self.setting_updated(new)
        return new

    async def user_created_new_wallet(self):
        new = BackupInitialized(user_initialized=True,
          user_skipped=False,
          backup_info_imported=False,
          new_wallet=True)
        await self.setting_updated(new)
        return new

    def get_backup_settings(self) -> BackupInitialized:
        return self.settings[BackupInitialized.__name__]