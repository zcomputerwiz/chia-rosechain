# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\bech32m.py
__doc__ = 'Reference implementation for Bech32m and segwit addresses.'
from typing import List, Optional, Tuple
from chia.types.blockchain_format.sized_bytes import bytes32
CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'

def bech32_polymod(values: List[int]) -> int:
    """Internal function that computes the Bech32 checksum."""
    generator = [
     996825010,642813549,513874426,1027748829,705979059]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 33554431) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if top >> i & 1 else 0

    return chk


def bech32_hrp_expand(hrp: str) -> List[int]:
    """Expand the HRP into values for checksum computation."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


M = 734539939

def bech32_verify_checksum(hrp: str, data: List[int]) -> bool:
    return bech32_polymod(bech32_hrp_expand(hrp) + data) == M


def bech32_create_checksum(hrp: str, data: List[int]) -> List[int]:
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0,0,0,0,0,0]) ^ M
    return [polymod >> 5 * (5 - i) & 31 for i in range(6)]


def bech32_encode(hrp: str, data: List[int]) -> str:
    """Compute a Bech32 string given HRP and data values."""
    combined = data + bech32_create_checksum(hrp, data)
    return hrp + '1' + ''.join([CHARSET[d] for d in combined])


def bech32_decode(bech: str) -> Tuple[(Optional[str], Optional[List[int]])]:
    """Validate a Bech32 string, and determine HRP and data."""
    if not any((ord(x) < 33 or ord(x) > 126 for x in bech)):
        if not bech.lower() != bech or bech.upper() != bech:
            return (None, None)
        bech = bech.lower()
        pos = bech.rfind('1')
        if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
            return (None, None)
        if not all((x in CHARSET for x in bech[pos + 1:])):
            return (None, None)
        hrp = bech[:pos]
        data = [CHARSET.find(x) for x in bech[pos + 1:]]
        if not bech32_verify_checksum(hrp, data):
            return (None, None)
        return (hrp, data[:-6])


def convertbits(data: List[int], frombits: int, tobits: int, pad: bool=True) -> List[int]:
    """General power-of-2 base conversion."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << frombits + tobits - 1) - 1
    for value in data:
        if value < 0 or value >> frombits:
            raise ValueError('Invalid Value')
        else:
            acc = (acc << frombits | value) & max_acc
            bits += frombits
            while bits >= tobits:
                bits -= tobits
                ret.append(acc >> bits & maxv)

    if pad:
        if bits:
            ret.append(acc << tobits - bits & maxv)
    else:
        if bits >= frombits or acc << tobits - bits & maxv:
            raise ValueError('Invalid bits')
    return ret


def encode_puzzle_hash(puzzle_hash: bytes32, prefix: str) -> str:
    encoded = bech32_encode(prefix, convertbits(puzzle_hash, 8, 5))
    return encoded


def decode_puzzle_hash(address: str) -> bytes32:
    hrpgot, data = bech32_decode(address)
    if data is None:
        raise ValueError('Invalid Address')
    decoded = convertbits(data, 5, 8, False)
    decoded_bytes = bytes(decoded)
    return decoded_bytes