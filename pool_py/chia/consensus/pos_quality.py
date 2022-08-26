# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\pos_quality.py
from chia.util.ints import uint64
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.762

def _expected_plot_size(k: int) -> uint64:
    """
    Given the plot size parameter k (which is between 32 and 59), computes the
    expected size of the plot in bytes (times a constant factor). This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte. The +1 is added to give half a bit more space per entry, which
    is necessary to store the entries in the plot.
    """
    return (2 * k + 1) * 2 ** (k - 1)