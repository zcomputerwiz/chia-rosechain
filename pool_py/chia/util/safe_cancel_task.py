# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\safe_cancel_task.py
import asyncio, logging
from typing import Optional

def cancel_task_safe(task: Optional[asyncio.Task], log: Optional[logging.Logger]=None):
    if task is not None:
        try:
            task.cancel()
        except Exception as e:
            try:
                if log is not None:
                    log.error(f"Error while canceling task.{e} {task}")
            finally:
                e = None
                del e