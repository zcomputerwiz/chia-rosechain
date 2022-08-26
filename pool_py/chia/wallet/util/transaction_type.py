# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\util\transaction_type.py
from enum import IntEnum

class TransactionType(IntEnum):
    INCOMING_TX = 0
    OUTGOING_TX = 1
    COINBASE_REWARD = 2
    FEE_REWARD = 3
    INCOMING_TRADE = 4
    OUTGOING_TRADE = 5