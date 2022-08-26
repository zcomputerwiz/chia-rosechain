# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\consensus\difficulty_adjustment.py
from typing import List, Optional, Tuple
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.significant_bits import count_significant_bits, truncate_to_significant_bits

def _get_blocks_at_height(blocks: BlockchainInterface, prev_b: BlockRecord, target_height: uint32, max_num_blocks: uint32=uint32(1)) -> List[BlockRecord]:
    """
    Return a consecutive list of BlockRecords starting at target_height, returning a maximum of
    max_num_blocks. Assumes all block records are present. Does a slot linear search, if the blocks are not
    in the path of the peak. Can only fetch ancestors of prev_b.

    Args:
        blocks: dict from header hash to BlockRecord.
        prev_b: prev_b (to start backwards search).
        target_height: target block to start
        max_num_blocks: max number of blocks to fetch (although less might be fetched)

    """
    if blocks.contains_height(prev_b.height):
        header_hash = blocks.height_to_hash(prev_b.height)
        if header_hash == prev_b.header_hash:
            block_list = []
            for h in range(target_height, target_height + max_num_blocks):
                if not blocks.contains_height(uint32(h)):
                    raise AssertionError
                else:
                    block_list.append(blocks.height_to_block_record(uint32(h)))

            return block_list
    curr_b = prev_b
    target_blocks = []
    while curr_b.height >= target_height:
        if curr_b.height < target_height + max_num_blocks:
            target_blocks.append(curr_b)
        if curr_b.height == 0:
            break
        else:
            curr_b = blocks.block_record(curr_b.prev_hash)

    return list(reversed(target_blocks))


def _get_second_to_last_transaction_block_in_previous_epoch(constants, blocks, last_b):
    """
    Retrieves the second to last transaction block in the previous epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dict from header hash to block of all relevant blocks
        last_b: last-block in the current epoch, or last block we have seen, if potentially finishing epoch soon

           prev epoch surpassed  prev epoch started                  epoch sur.  epoch started
            v                       v                                v         v
      |.B...B....B. B....B...|......B....B.....B...B.|.B.B.B..|..B...B.B.B...|.B.B.B. B.|........
            PREV EPOCH                 CURR EPOCH                               NEW EPOCH

     The blocks selected for the timestamps are the second to last transaction blocks in each epoch.
     Block at height 0 is an exception. Note that H mod EPOCH_BLOCKS where H is the height of the first block in the
     epoch, must be >= 0, and < 128.
    """
    height_in_next_epoch = last_b.height + 2 * constants.MAX_SUB_SLOT_BLOCKS + constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 5
    height_epoch_surpass = uint32(height_in_next_epoch - height_in_next_epoch % constants.EPOCH_BLOCKS)
    height_prev_epoch_surpass = uint32(height_epoch_surpass - constants.EPOCH_BLOCKS)
    if not height_prev_epoch_surpass % constants.EPOCH_BLOCKS== height_prev_epoch_surpass % constants.EPOCH_BLOCKS == 0:
        raise AssertionError
    assert height_in_next_epoch - height_epoch_surpass < 5 * constants.MAX_SUB_SLOT_BLOCKS
    if height_prev_epoch_surpass == 0:
        return _get_blocks_at_height(blocks, last_b, uint32(0))[0]
    fetched_blocks = _get_blocks_at_height(blocks, last_b, uint32(height_prev_epoch_surpass - constants.MAX_SUB_SLOT_BLOCKS - 1), uint32(3 * constants.MAX_SUB_SLOT_BLOCKS + constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 3))
    fetched_index = constants.MAX_SUB_SLOT_BLOCKS
    curr_b = fetched_blocks[fetched_index]
    fetched_index += 1
    assert curr_b.height == height_prev_epoch_surpass - 1
    next_b = fetched_blocks[fetched_index]
    assert next_b.height == height_prev_epoch_surpass
    while next_b.sub_epoch_summary_included is None:
        curr_b = next_b
        next_b = fetched_blocks[fetched_index]
        fetched_index += 1

    found_tx_block = 1 if curr_b.is_transaction_block else 0
    while found_tx_block < 2:
        curr_b = blocks.block_record(curr_b.prev_hash)
        if curr_b.is_transaction_block:
            found_tx_block += 1

    return curr_b


def height_can_be_first_in_epoch(constants: ConsensusConstants, height: uint32) -> bool:
    return (height - height % constants.SUB_EPOCH_BLOCKS) % constants.EPOCH_BLOCKS == 0


def can_finish_sub_and_full_epoch(constants: ConsensusConstants, blocks: BlockchainInterface, height: uint32, prev_header_hash: Optional[bytes32], deficit: uint8, block_at_height_included_ses: bool) -> Tuple[(bool, bool)]:
    """
    Returns a bool tuple
    first bool is true if the next sub-slot after height will form part of a new sub-epoch. Therefore
    block height is the last block, and height + 1 is in a new sub-epoch.
    second bool is true if the next sub-slot after height will form part of a new sub-epoch and epoch.
    Therefore, block height is the last block, and height + 1 is in a new epoch.

    Args:
        constants: consensus constants being used for this chain
        blocks: dictionary from header hash to SBR of all included SBR
        height: block height of the (potentially) last block in the sub-epoch
        prev_header_hash: prev_header hash of the block at height, assuming not genesis
        deficit: deficit of block at height height
        block_at_height_included_ses: whether or not the block at height height already included a SES
    """
    if height < constants.SUB_EPOCH_BLOCKS - 1:
        return (False, False)
    assert prev_header_hash is not None
    if deficit > 0:
        return (False, False)
    if block_at_height_included_ses:
        return (False, False)
    if (height + 1) % constants.SUB_EPOCH_BLOCKS > 1:
        curr = blocks.block_record(prev_header_hash)
        while curr.height % constants.SUB_EPOCH_BLOCKS > 0:
            if curr.sub_epoch_summary_included is not None:
                return (False, False)
            else:
                curr = blocks.block_record(curr.prev_hash)

        if curr.sub_epoch_summary_included is not None:
            return (False, False)
    return (
     True, height_can_be_first_in_epoch(constants, uint32(height + 1)))


def _get_next_sub_slot_iters--- This code section failed: ---

 L. 220         0  LOAD_GLOBAL              uint32
                2  LOAD_FAST                'height'
                4  LOAD_CONST               1
                6  BINARY_ADD       
                8  CALL_FUNCTION_1       1  '1 positional argument'
               10  STORE_FAST               'next_height'

 L. 222        12  LOAD_FAST                'next_height'
               14  LOAD_FAST                'constants'
               16  LOAD_ATTR                EPOCH_BLOCKS
               18  COMPARE_OP               <
               20  POP_JUMP_IF_FALSE    32  'to 32'

 L. 223        22  LOAD_GLOBAL              uint64
               24  LOAD_FAST                'constants'
               26  LOAD_ATTR                SUB_SLOT_ITERS_STARTING
               28  CALL_FUNCTION_1       1  '1 positional argument'
               30  RETURN_VALUE     
             32_0  COME_FROM            20  '20'

 L. 225        32  LOAD_FAST                'blocks'
               34  LOAD_METHOD              contains_block
               36  LOAD_FAST                'prev_header_hash'
               38  CALL_METHOD_1         1  '1 positional argument'
               40  POP_JUMP_IF_TRUE     58  'to 58'

 L. 226        42  LOAD_GLOBAL              ValueError
               44  LOAD_STR                 'Header hash '
               46  LOAD_FAST                'prev_header_hash'
               48  FORMAT_VALUE          0  ''
               50  LOAD_STR                 ' not in blocks'
               52  BUILD_STRING_3        3 
               54  CALL_FUNCTION_1       1  '1 positional argument'
               56  RAISE_VARARGS_1       1  'exception instance'
             58_0  COME_FROM            40  '40'

 L. 228        58  LOAD_FAST                'blocks'
               60  LOAD_METHOD              block_record
               62  LOAD_FAST                'prev_header_hash'
               64  CALL_METHOD_1         1  '1 positional argument'
               66  STORE_FAST               'prev_b'

 L. 231        68  LOAD_FAST                'skip_epoch_check'
               70  POP_JUMP_IF_TRUE    106  'to 106'

 L. 232        72  LOAD_GLOBAL              can_finish_sub_and_full_epoch

 L. 233        74  LOAD_FAST                'constants'
               76  LOAD_FAST                'blocks'
               78  LOAD_FAST                'height'
               80  LOAD_FAST                'prev_header_hash'
               82  LOAD_FAST                'deficit'
               84  LOAD_FAST                'block_at_height_included_ses'
               86  CALL_FUNCTION_6       6  '6 positional arguments'
               88  UNPACK_SEQUENCE_2     2 
               90  STORE_FAST               '_'
               92  STORE_FAST               'can_finish_epoch'

 L. 235        94  LOAD_FAST                'new_slot'
               96  POP_JUMP_IF_FALSE   102  'to 102'
               98  LOAD_FAST                'can_finish_epoch'
              100  POP_JUMP_IF_TRUE    106  'to 106'
            102_0  COME_FROM            96  '96'

 L. 236       102  LOAD_FAST                'curr_sub_slot_iters'
              104  RETURN_VALUE     
            106_0  COME_FROM           100  '100'
            106_1  COME_FROM            70  '70'

 L. 238       106  LOAD_GLOBAL              _get_second_to_last_transaction_block_in_previous_epoch
              108  LOAD_FAST                'constants'
              110  LOAD_FAST                'blocks'
              112  LOAD_FAST                'prev_b'
              114  CALL_FUNCTION_3       3  '3 positional arguments'
              116  STORE_FAST               'last_block_prev'

 L. 245       118  LOAD_FAST                'prev_b'
              120  STORE_FAST               'last_block_curr'

 L. 246       122  SETUP_LOOP          156  'to 156'
            124_0  COME_FROM           152  '152'
              124  LOAD_FAST                'last_block_curr'
              126  LOAD_ATTR                total_iters
              128  LOAD_FAST                'signage_point_total_iters'
              130  COMPARE_OP               >
              132  POP_JUMP_IF_TRUE    140  'to 140'
              134  LOAD_FAST                'last_block_curr'
              136  LOAD_ATTR                is_transaction_block
              138  POP_JUMP_IF_TRUE    154  'to 154'
            140_0  COME_FROM           132  '132'

 L. 247       140  LOAD_FAST                'blocks'
              142  LOAD_METHOD              block_record
              144  LOAD_FAST                'last_block_curr'
              146  LOAD_ATTR                prev_hash
              148  CALL_METHOD_1         1  '1 positional argument'
              150  STORE_FAST               'last_block_curr'
              152  JUMP_LOOP           124  'to 124'
            154_0  COME_FROM           138  '138'
              154  POP_BLOCK        
            156_0  COME_FROM_LOOP      122  '122'

 L. 248       156  LOAD_FAST                'last_block_curr'
              158  LOAD_ATTR                timestamp
              160  LOAD_CONST               None
              162  COMPARE_OP               is-not
              164  POP_JUMP_IF_FALSE   176  'to 176'
              166  LOAD_FAST                'last_block_prev'
              168  LOAD_ATTR                timestamp
              170  LOAD_CONST               None
              172  COMPARE_OP               is-not
              174  POP_JUMP_IF_TRUE    180  'to 180'
            176_0  COME_FROM           164  '164'
              176  LOAD_ASSERT              AssertionError
              178  RAISE_VARARGS_1       1  'exception instance'
            180_0  COME_FROM           174  '174'

 L. 251       180  LOAD_GLOBAL              uint64

 L. 254       182  LOAD_FAST                'constants'
              184  LOAD_ATTR                SUB_SLOT_TIME_TARGET
              186  LOAD_FAST                'last_block_curr'
              188  LOAD_ATTR                total_iters
              190  LOAD_FAST                'last_block_prev'
              192  LOAD_ATTR                total_iters
              194  BINARY_SUBTRACT  
              196  BINARY_MULTIPLY  
              198  LOAD_FAST                'last_block_curr'
              200  LOAD_ATTR                timestamp
              202  LOAD_FAST                'last_block_prev'
              204  LOAD_ATTR                timestamp
              206  BINARY_SUBTRACT  
              208  BINARY_FLOOR_DIVIDE
              210  CALL_FUNCTION_1       1  '1 positional argument'
              212  STORE_FAST               'new_ssi_precise'

 L. 258       214  LOAD_GLOBAL              uint64
              216  LOAD_FAST                'constants'
              218  LOAD_ATTR                DIFFICULTY_CHANGE_MAX_FACTOR
              220  LOAD_FAST                'last_block_curr'
              222  LOAD_ATTR                sub_slot_iters
              224  BINARY_MULTIPLY  
              226  CALL_FUNCTION_1       1  '1 positional argument'
              228  STORE_FAST               'max_ssi'

 L. 259       230  LOAD_GLOBAL              uint64
              232  LOAD_FAST                'last_block_curr'
              234  LOAD_ATTR                sub_slot_iters
              236  LOAD_FAST                'constants'
              238  LOAD_ATTR                DIFFICULTY_CHANGE_MAX_FACTOR
              240  BINARY_FLOOR_DIVIDE
              242  CALL_FUNCTION_1       1  '1 positional argument'
              244  STORE_FAST               'min_ssi'

 L. 260       246  LOAD_FAST                'new_ssi_precise'
              248  LOAD_FAST                'last_block_curr'
              250  LOAD_ATTR                sub_slot_iters
              252  COMPARE_OP               >=
          254_256  POP_JUMP_IF_FALSE   274  'to 274'

 L. 261       258  LOAD_GLOBAL              uint64
              260  LOAD_GLOBAL              min
              262  LOAD_FAST                'new_ssi_precise'
              264  LOAD_FAST                'max_ssi'
              266  CALL_FUNCTION_2       2  '2 positional arguments'
              268  CALL_FUNCTION_1       1  '1 positional argument'
              270  STORE_FAST               'new_ssi_precise'
              272  JUMP_FORWARD        294  'to 294'
            274_0  COME_FROM           254  '254'

 L. 263       274  LOAD_GLOBAL              uint64
              276  LOAD_GLOBAL              max
              278  LOAD_FAST                'constants'
              280  LOAD_ATTR                NUM_SPS_SUB_SLOT
              282  LOAD_FAST                'new_ssi_precise'
              284  LOAD_FAST                'min_ssi'
              286  BUILD_LIST_3          3 
              288  CALL_FUNCTION_1       1  '1 positional argument'
              290  CALL_FUNCTION_1       1  '1 positional argument'
              292  STORE_FAST               'new_ssi_precise'
            294_0  COME_FROM           272  '272'

 L. 265       294  LOAD_GLOBAL              truncate_to_significant_bits
              296  LOAD_FAST                'new_ssi_precise'
              298  LOAD_FAST                'constants'
              300  LOAD_ATTR                SIGNIFICANT_BITS
              302  CALL_FUNCTION_2       2  '2 positional arguments'
              304  STORE_FAST               'new_ssi'

 L. 266       306  LOAD_GLOBAL              uint64
              308  LOAD_FAST                'new_ssi'
              310  LOAD_FAST                'new_ssi'
              312  LOAD_FAST                'constants'
              314  LOAD_ATTR                NUM_SPS_SUB_SLOT
              316  BINARY_MODULO    
              318  BINARY_SUBTRACT  
              320  CALL_FUNCTION_1       1  '1 positional argument'
              322  STORE_FAST               'new_ssi'

 L. 267       324  LOAD_GLOBAL              count_significant_bits
              326  LOAD_FAST                'new_ssi'
              328  CALL_FUNCTION_1       1  '1 positional argument'
              330  LOAD_FAST                'constants'
              332  LOAD_ATTR                SIGNIFICANT_BITS
              334  COMPARE_OP               <=
          336_338  POP_JUMP_IF_TRUE    344  'to 344'
              340  LOAD_ASSERT              AssertionError
              342  RAISE_VARARGS_1       1  'exception instance'
            344_0  COME_FROM           336  '336'

 L. 268       344  LOAD_FAST                'new_ssi'
              346  RETURN_VALUE     
               -1  RETURN_LAST      

Parse error at or near `LOAD_FAST' instruction at offset 156


def _get_next_difficulty--- This code section failed: ---

 L. 299         0  LOAD_GLOBAL              uint32
                2  LOAD_FAST                'height'
                4  LOAD_CONST               1
                6  BINARY_ADD       
                8  CALL_FUNCTION_1       1  '1 positional argument'
               10  STORE_FAST               'next_height'

 L. 301        12  LOAD_FAST                'next_height'
               14  LOAD_FAST                'constants'
               16  LOAD_ATTR                EPOCH_BLOCKS
               18  LOAD_CONST               3
               20  LOAD_FAST                'constants'
               22  LOAD_ATTR                MAX_SUB_SLOT_BLOCKS
               24  BINARY_MULTIPLY  
               26  BINARY_SUBTRACT  
               28  COMPARE_OP               <
               30  POP_JUMP_IF_FALSE    42  'to 42'

 L. 303        32  LOAD_GLOBAL              uint64
               34  LOAD_FAST                'constants'
               36  LOAD_ATTR                DIFFICULTY_STARTING
               38  CALL_FUNCTION_1       1  '1 positional argument'
               40  RETURN_VALUE     
             42_0  COME_FROM            30  '30'

 L. 305        42  LOAD_FAST                'blocks'
               44  LOAD_METHOD              contains_block
               46  LOAD_FAST                'prev_header_hash'
               48  CALL_METHOD_1         1  '1 positional argument'
               50  POP_JUMP_IF_TRUE     68  'to 68'

 L. 306        52  LOAD_GLOBAL              ValueError
               54  LOAD_STR                 'Header hash '
               56  LOAD_FAST                'prev_header_hash'
               58  FORMAT_VALUE          0  ''
               60  LOAD_STR                 ' not in blocks'
               62  BUILD_STRING_3        3 
               64  CALL_FUNCTION_1       1  '1 positional argument'
               66  RAISE_VARARGS_1       1  'exception instance'
             68_0  COME_FROM            50  '50'

 L. 308        68  LOAD_FAST                'blocks'
               70  LOAD_METHOD              block_record
               72  LOAD_FAST                'prev_header_hash'
               74  CALL_METHOD_1         1  '1 positional argument'
               76  STORE_FAST               'prev_b'

 L. 311        78  LOAD_FAST                'skip_epoch_check'
               80  POP_JUMP_IF_TRUE    116  'to 116'

 L. 312        82  LOAD_GLOBAL              can_finish_sub_and_full_epoch

 L. 313        84  LOAD_FAST                'constants'
               86  LOAD_FAST                'blocks'
               88  LOAD_FAST                'height'
               90  LOAD_FAST                'prev_header_hash'
               92  LOAD_FAST                'deficit'
               94  LOAD_FAST                'block_at_height_included_ses'
               96  CALL_FUNCTION_6       6  '6 positional arguments'
               98  UNPACK_SEQUENCE_2     2 
              100  STORE_FAST               '_'
              102  STORE_FAST               'can_finish_epoch'

 L. 315       104  LOAD_FAST                'new_slot'
              106  POP_JUMP_IF_FALSE   112  'to 112'
              108  LOAD_FAST                'can_finish_epoch'
              110  POP_JUMP_IF_TRUE    116  'to 116'
            112_0  COME_FROM           106  '106'

 L. 316       112  LOAD_FAST                'current_difficulty'
              114  RETURN_VALUE     
            116_0  COME_FROM           110  '110'
            116_1  COME_FROM            80  '80'

 L. 318       116  LOAD_GLOBAL              _get_second_to_last_transaction_block_in_previous_epoch
              118  LOAD_FAST                'constants'
              120  LOAD_FAST                'blocks'
              122  LOAD_FAST                'prev_b'
              124  CALL_FUNCTION_3       3  '3 positional arguments'
              126  STORE_FAST               'last_block_prev'

 L. 325       128  LOAD_FAST                'prev_b'
              130  STORE_FAST               'last_block_curr'

 L. 326       132  SETUP_LOOP          166  'to 166'
            134_0  COME_FROM           162  '162'
              134  LOAD_FAST                'last_block_curr'
              136  LOAD_ATTR                total_iters
              138  LOAD_FAST                'signage_point_total_iters'
              140  COMPARE_OP               >
              142  POP_JUMP_IF_TRUE    150  'to 150'
              144  LOAD_FAST                'last_block_curr'
              146  LOAD_ATTR                is_transaction_block
              148  POP_JUMP_IF_TRUE    164  'to 164'
            150_0  COME_FROM           142  '142'

 L. 327       150  LOAD_FAST                'blocks'
              152  LOAD_METHOD              block_record
              154  LOAD_FAST                'last_block_curr'
              156  LOAD_ATTR                prev_hash
              158  CALL_METHOD_1         1  '1 positional argument'
              160  STORE_FAST               'last_block_curr'
              162  JUMP_LOOP           134  'to 134'
            164_0  COME_FROM           148  '148'
              164  POP_BLOCK        
            166_0  COME_FROM_LOOP      132  '132'

 L. 329       166  LOAD_FAST                'last_block_curr'
              168  LOAD_ATTR                timestamp
              170  LOAD_CONST               None
              172  COMPARE_OP               is-not
              174  POP_JUMP_IF_TRUE    180  'to 180'
              176  LOAD_ASSERT              AssertionError
              178  RAISE_VARARGS_1       1  'exception instance'
            180_0  COME_FROM           174  '174'

 L. 330       180  LOAD_FAST                'last_block_prev'
              182  LOAD_ATTR                timestamp
              184  LOAD_CONST               None
              186  COMPARE_OP               is-not
              188  POP_JUMP_IF_TRUE    194  'to 194'
              190  LOAD_ASSERT              AssertionError
              192  RAISE_VARARGS_1       1  'exception instance'
            194_0  COME_FROM           188  '188'

 L. 331       194  LOAD_GLOBAL              uint64
              196  LOAD_FAST                'last_block_curr'
              198  LOAD_ATTR                timestamp
              200  LOAD_FAST                'last_block_prev'
              202  LOAD_ATTR                timestamp
              204  BINARY_SUBTRACT  
              206  CALL_FUNCTION_1       1  '1 positional argument'
              208  STORE_FAST               'actual_epoch_time'

 L. 333       210  LOAD_GLOBAL              uint64
              212  LOAD_FAST                'prev_b'
              214  LOAD_ATTR                weight
              216  LOAD_FAST                'blocks'
              218  LOAD_METHOD              block_record
              220  LOAD_FAST                'prev_b'
              222  LOAD_ATTR                prev_hash
              224  CALL_METHOD_1         1  '1 positional argument'
              226  LOAD_ATTR                weight
              228  BINARY_SUBTRACT  
              230  CALL_FUNCTION_1       1  '1 positional argument'
              232  STORE_FAST               'old_difficulty'

 L. 336       234  LOAD_GLOBAL              uint64

 L. 339       236  LOAD_FAST                'last_block_curr'
              238  LOAD_ATTR                weight
              240  LOAD_FAST                'last_block_prev'
              242  LOAD_ATTR                weight
              244  BINARY_SUBTRACT  
              246  LOAD_FAST                'constants'
              248  LOAD_ATTR                SUB_SLOT_TIME_TARGET
              250  BINARY_MULTIPLY  
              252  LOAD_FAST                'constants'
              254  LOAD_ATTR                SLOT_BLOCKS_TARGET
              256  LOAD_FAST                'actual_epoch_time'
              258  BINARY_MULTIPLY  
              260  BINARY_FLOOR_DIVIDE
              262  CALL_FUNCTION_1       1  '1 positional argument'
              264  STORE_FAST               'new_difficulty_precise'

 L. 343       266  LOAD_GLOBAL              uint64
              268  LOAD_FAST                'constants'
              270  LOAD_ATTR                DIFFICULTY_CHANGE_MAX_FACTOR
              272  LOAD_FAST                'old_difficulty'
              274  BINARY_MULTIPLY  
              276  CALL_FUNCTION_1       1  '1 positional argument'
              278  STORE_FAST               'max_diff'

 L. 344       280  LOAD_GLOBAL              uint64
              282  LOAD_FAST                'old_difficulty'
              284  LOAD_FAST                'constants'
              286  LOAD_ATTR                DIFFICULTY_CHANGE_MAX_FACTOR
              288  BINARY_FLOOR_DIVIDE
              290  CALL_FUNCTION_1       1  '1 positional argument'
              292  STORE_FAST               'min_diff'

 L. 346       294  LOAD_FAST                'new_difficulty_precise'
              296  LOAD_FAST                'old_difficulty'
              298  COMPARE_OP               >=
          300_302  POP_JUMP_IF_FALSE   320  'to 320'

 L. 347       304  LOAD_GLOBAL              uint64
              306  LOAD_GLOBAL              min
              308  LOAD_FAST                'new_difficulty_precise'
              310  LOAD_FAST                'max_diff'
              312  CALL_FUNCTION_2       2  '2 positional arguments'
              314  CALL_FUNCTION_1       1  '1 positional argument'
              316  STORE_FAST               'new_difficulty_precise'
              318  JUMP_FORWARD        342  'to 342'
            320_0  COME_FROM           300  '300'

 L. 349       320  LOAD_GLOBAL              uint64
              322  LOAD_GLOBAL              max
              324  LOAD_GLOBAL              uint64
              326  LOAD_CONST               1
              328  CALL_FUNCTION_1       1  '1 positional argument'
              330  LOAD_FAST                'new_difficulty_precise'
              332  LOAD_FAST                'min_diff'
              334  BUILD_LIST_3          3 
              336  CALL_FUNCTION_1       1  '1 positional argument'
              338  CALL_FUNCTION_1       1  '1 positional argument'
              340  STORE_FAST               'new_difficulty_precise'
            342_0  COME_FROM           318  '318'

 L. 350       342  LOAD_GLOBAL              truncate_to_significant_bits
              344  LOAD_FAST                'new_difficulty_precise'
              346  LOAD_FAST                'constants'
              348  LOAD_ATTR                SIGNIFICANT_BITS
              350  CALL_FUNCTION_2       2  '2 positional arguments'
              352  STORE_FAST               'new_difficulty'

 L. 351       354  LOAD_GLOBAL              count_significant_bits
              356  LOAD_FAST                'new_difficulty'
              358  CALL_FUNCTION_1       1  '1 positional argument'
              360  LOAD_FAST                'constants'
              362  LOAD_ATTR                SIGNIFICANT_BITS
              364  COMPARE_OP               <=
          366_368  POP_JUMP_IF_TRUE    374  'to 374'
              370  LOAD_ASSERT              AssertionError
              372  RAISE_VARARGS_1       1  'exception instance'
            374_0  COME_FROM           366  '366'

 L. 352       374  LOAD_GLOBAL              uint64
              376  LOAD_FAST                'new_difficulty'
              378  CALL_FUNCTION_1       1  '1 positional argument'
              380  RETURN_VALUE     
               -1  RETURN_LAST      

Parse error at or near `LOAD_FAST' instruction at offset 166


def get_next_sub_slot_iters_and_difficulty(constants: ConsensusConstants, is_first_in_sub_slot: bool, prev_b: Optional[BlockRecord], blocks: BlockchainInterface) -> Tuple[(uint64, uint64)]:
    """
    Retrieves the current sub_slot iters and difficulty of the next block after prev_b.

    Args:
        constants: consensus constants being used for this chain
        is_first_in_sub_slot: Whether the next block is the first in the sub slot
        prev_b: the previous block (last block in the epoch)
        blocks: dictionary from header hash to SBR of all included SBR

    """
    if prev_b is None:
        return (constants.SUB_SLOT_ITERS_STARTING, constants.DIFFICULTY_STARTING)
    if prev_b.height != 0:
        prev_difficulty = uint64(prev_b.weight - blocks.block_record(prev_b.prev_hash).weight)
    else:
        prev_difficulty = uint64(prev_b.weight)
    if prev_b.sub_epoch_summary_included is not None:
        return (prev_b.sub_slot_iters, prev_difficulty)
    sp_total_iters = prev_b.sp_total_iters(constants)
    difficulty = _get_next_difficulty(constants, blocks, prev_b.prev_hash, prev_b.height, prev_difficulty, prev_b.deficit, False, is_first_in_sub_slot, sp_total_iters)
    sub_slot_iters = _get_next_sub_slot_iters(constants, blocks, prev_b.prev_hash, prev_b.height, prev_b.sub_slot_iters, prev_b.deficit, False, is_first_in_sub_slot, sp_total_iters)
    return (
     sub_slot_iters, difficulty)