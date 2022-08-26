# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\significant_bits.py


def truncate_to_significant_bits(input_x: int, num_significant_bits: int) -> int:
    """
    Truncates the number such that only the top num_significant_bits contain 1s.
    and the rest of the number is 0s (in binary). Ignores decimals and leading
    zeroes. For example, -0b011110101 and 2, returns -0b11000000.
    """
    x = abs(input_x)
    if num_significant_bits > x.bit_length():
        return x
    lower = x.bit_length() - num_significant_bits
    mask = (1 << x.bit_length()) - 1 - ((1 << lower) - 1)
    if input_x < 0:
        return -(x & mask)
    return x & mask


def count_significant_bits(input_x: int) -> int:
    """
    Counts the number of significant bits of an integer, ignoring negative signs
    and leading zeroes. For example, for -0b000110010000, returns 5.
    """
    x = input_x
    for i in range(x.bit_length()):
        if x & 1 << i > 0:
            return x.bit_length() - i

    return 0