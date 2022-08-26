# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\settings\settings_objects.py
from dataclasses import dataclass
from chia.util.streamable import Streamable, streamable

@dataclass(frozen=True)
@streamable
class BackupInitialized(Streamable):
    __doc__ = '\n    Stores user decision regarding import of backup info\n    '
    user_initialized: bool
    user_skipped: bool
    backup_info_imported: bool
    new_wallet: bool