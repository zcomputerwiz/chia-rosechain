# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\recursive_replace.py
from dataclasses import replace
from typing import Any

def recursive_replace(root_obj, replace_str, replace_with):
    split_str = replace_str.split('.')
    if len(split_str) == 1:
        return replace(root_obj, **{split_str[0]: replace_with})
    sub_obj = recursive_replace(getattr(root_obj, split_str[0]), '.'.join(split_str[1:]), replace_with)
    return replace(root_obj, **{split_str[0]: sub_obj})