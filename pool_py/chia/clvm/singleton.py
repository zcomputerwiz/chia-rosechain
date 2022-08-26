# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\clvm\singleton.py
import chia.wallet.puzzles.load_clvm as load_clvm
P2_SINGLETON_MOD = load_clvm('p2_singleton.clvm')
SINGLETON_TOP_LAYER_MOD = load_clvm('singleton_top_layer.clvm')
SINGLETON_LAUNCHER = load_clvm('singleton_launcher.clvm')