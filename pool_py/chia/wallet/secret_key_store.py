# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\wallet\secret_key_store.py
from typing import Dict, Optional
from blspy import G1Element, PrivateKey
GROUP_ORDER = 52435875175126190479447740508185965837690552500527637822603658699938581184513

class SecretKeyStore:
    _pk2sk: Dict[(G1Element, PrivateKey)]

    def __init__(self):
        self._pk2sk = {}

    def save_secret_key(self, secret_key: PrivateKey):
        public_key = secret_key.get_g1()
        self._pk2sk[bytes(public_key)] = secret_key

    def secret_key_for_public_key(self, public_key: G1Element) -> Optional[PrivateKey]:
        return self._pk2sk.get(bytes(public_key))