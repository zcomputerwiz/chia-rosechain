# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\default_root.py
import os
from pathlib import Path
DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv('CHIA_ROOT', '~/.chiarose/mainnet'))).resolve()