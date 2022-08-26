# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\setproctitle.py
try:
    import setproctitle as pysetproctitle
    no_setproctitle = False
except Exception:
    no_setproctitle = True

def setproctitle(ps_name: str) -> None:
    if no_setproctitle is False:
        pysetproctitle.setproctitle(ps_name)