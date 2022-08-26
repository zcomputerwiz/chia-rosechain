# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\full_node\weight_proof.py
import asyncio, dataclasses, logging, math, random
from concurrent.futures.process import ProcessPoolExecutor
from typing import Dict, List, Optional, Tuple
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import header_block_to_sub_block_record
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_iters, is_overflow_block
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochData, SubSlotData, WeightProof, SubEpochSegments, RecentChainData
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import dataclass_from_dict, recurse_jsonify
log = logging.getLogger(__name__)

class WeightProofHandler:
    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20

    def __init__(self, constants: ConsensusConstants, blockchain: BlockchainInterface):
        self.tip = None
        self.proof = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()

    async def get_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error('unknown tip')
            return
        if tip_rec.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            log.debug('chain to short for weight proof')
            return
        async with self.lock:
            if self.proof is not None:
                if self.proof.recent_chain_data[-1].header_hash == tip:
                    return self.proof
            wp = await self._create_proof_of_weight(tip)
            if wp is None:
                return
            self.proof = wp
            self.tip = tip
            return wp

    def get_sub_epoch_data(self, tip_height: uint32, summary_heights: List[uint32]) -> List[SubEpochData]:
        sub_epoch_data = []
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > tip_height:
                break
            else:
                ses = self.blockchain.get_ses(ses_height)
                log.debug(f"handle sub epoch summary {sub_epoch_n} at height: {ses_height} ses {ses}")
                sub_epoch_data.append(_create_sub_epoch_data(ses))

        return sub_epoch_data

    async def _create_proof_of_weight(self, tip: bytes32) -> Optional[WeightProof]:
        """
        Creates a weight proof object
        """
        assert self.blockchain is not None
        sub_epoch_segments = []
        tip_rec = self.blockchain.try_block_record(tip)
        if tip_rec is None:
            log.error('failed not tip in cache')
            return
        log.info(f"create weight proof peak {tip} {tip_rec.height}")
        recent_chain = await self._get_recent_chain(tip_rec.height)
        if recent_chain is None:
            return
        summary_heights = self.blockchain.get_ses_heights()
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return
        sub_epoch_data = self.get_sub_epoch_data(tip_rec.height, summary_heights)
        seed = self.get_seed_for_proof(summary_heights, tip_rec.height)
        rng = random.Random(seed)
        weight_to_check = _get_weights_for_sampling(rng, tip_rec.weight, recent_chain)
        sample_n = 0
        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            return
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            if ses_height > tip_rec.height:
                break
            if sample_n >= self.MAX_SAMPLES:
                log.debug('reached sampled sub epoch cap')
                break
            else:
                ses_block = ses_blocks[sub_epoch_n]
                if ses_block is None or ses_block.sub_epoch_summary_included is None:
                    log.error('error while building proof')
                    return
                if _sample_sub_epoch(prev_ses_block.weight, ses_block.weight, weight_to_check):
                    sample_n += 1
                    segments = await self.blockchain.get_sub_epoch_challenge_segments(ses_block.header_hash)
                    if segments is None:
                        segments = await self._WeightProofHandler__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
                        if segments is None:
                            log.error(f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} ")
                            return
                        await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.header_hash, segments)
                    log.debug(f"sub epoch {sub_epoch_n} has {len(segments)} segments")
                    sub_epoch_segments.extend(segments)
                prev_ses_block = ses_block

        log.debug(f"sub_epochs: {len(sub_epoch_data)}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, recent_chain)

    def get_seed_for_proof(self, summary_heights: List[uint32], tip_height) -> bytes32:
        count = 0
        ses = None
        for sub_epoch_n, ses_height in enumerate(reversed(summary_heights)):
            if ses_height <= tip_height:
                count += 1
            if count == 2:
                ses = self.blockchain.get_ses(ses_height)
                break

        assert ses is not None
        seed = ses.get_hash()
        return seed

    async def _get_recent_chain(self, tip_height: uint32) -> Optional[List[HeaderBlock]]:
        recent_chain = []
        ses_heights = self.blockchain.get_ses_heights()
        min_height = 0
        count_ses = 0
        for ses_height in reversed(ses_heights):
            if ses_height <= tip_height:
                count_ses += 1
            if count_ses == 2:
                min_height = ses_height - 1
                break

        log.debug(f"start {min_height} end {tip_height}")
        headers = await self.blockchain.get_header_blocks_in_range(min_height, tip_height, tx_filter=False)
        blocks = await self.blockchain.get_block_records_in_range(min_height, tip_height)
        ses_count = 0
        curr_height = tip_height
        blocks_n = 0
        while ses_count < 2:
            if curr_height == 0:
                break
            else:
                header_block = headers[self.blockchain.height_to_hash(curr_height)]
                block_rec = blocks[header_block.header_hash]
                if header_block is None:
                    log.error('creating recent chain failed')
                    return
                recent_chain.insert(0, header_block)
                if block_rec.sub_epoch_summary_included:
                    ses_count += 1
                curr_height = uint32(curr_height - 1)
                blocks_n += 1

        header_block = headers[self.blockchain.height_to_hash(curr_height)]
        recent_chain.insert(0, header_block)
        log.info(f"recent chain, start: {recent_chain[0].reward_chain_block.height} end:  {recent_chain[-1].reward_chain_block.height} ")
        return recent_chain

    async def create_prev_sub_epoch_segments(self):
        log.debug('create prev sub_epoch_segments')
        heights = self.blockchain.get_ses_heights()
        if len(heights) < 3:
            return
        count = len(heights) - 2
        ses_sub_block = self.blockchain.height_to_block_record(heights[-2])
        prev_ses_sub_block = self.blockchain.height_to_block_record(heights[-3])
        assert prev_ses_sub_block.sub_epoch_summary_included is not None
        segments = await self._WeightProofHandler__create_sub_epoch_segments(ses_sub_block, prev_ses_sub_block, uint32(count))
        assert segments is not None
        await self.blockchain.persist_sub_epoch_challenge_segments(ses_sub_block.header_hash, segments)
        log.debug('sub_epoch_segments done')

    async def create_sub_epoch_segments(self):
        log.debug('check segments in db')
        assert self.blockchain is not None
        peak_height = self.blockchain.get_peak_height()
        if peak_height is None:
            log.error('no peak yet')
            return
        summary_heights = self.blockchain.get_ses_heights()
        prev_ses_block = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(uint32(0)))
        if prev_ses_block is None:
            return
        ses_blocks = await self.blockchain.get_block_records_at(summary_heights)
        if ses_blocks is None:
            return
        for sub_epoch_n, ses_height in enumerate(summary_heights):
            log.debug(f"check db for sub epoch {sub_epoch_n}")
            if ses_height > peak_height:
                break
            else:
                ses_block = ses_blocks[sub_epoch_n]
                if ses_block is None or ses_block.sub_epoch_summary_included is None:
                    log.error('error while building proof')
                    return
                await self._WeightProofHandler__create_persist_segment(prev_ses_block, ses_block, ses_height, sub_epoch_n)
                prev_ses_block = ses_block
                await asyncio.sleep(2)

        log.debug('done checking segments')

    async def __create_persist_segment(self, prev_ses_block, ses_block, ses_height, sub_epoch_n):
        segments = await self.blockchain.get_sub_epoch_challenge_segments(ses_block.header_hash)
        if segments is None:
            segments = await self._WeightProofHandler__create_sub_epoch_segments(ses_block, prev_ses_block, uint32(sub_epoch_n))
            if segments is None:
                log.error(f"failed while building segments for sub epoch {sub_epoch_n}, ses height {ses_height} ")
                return
            await self.blockchain.persist_sub_epoch_challenge_segments(ses_block.header_hash, segments)

    async def __create_sub_epoch_segments(self, ses_block: BlockRecord, se_start: BlockRecord, sub_epoch_n: uint32) -> Optional[List[SubEpochChallengeSegment]]:
        segments = []
        start_height = await self.get_prev_two_slots_height(se_start)
        blocks = await self.blockchain.get_block_records_in_range(start_height, ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS)
        header_blocks = await self.blockchain.get_header_blocks_in_range(start_height,
          (ses_block.height + self.constants.MAX_SUB_SLOT_BLOCKS), tx_filter=False)
        curr = header_blocks[se_start.header_hash]
        height = se_start.height
        assert curr is not None
        first = True
        idx = 0
        while curr.height < ses_block.height:
            if blocks[curr.header_hash].is_challenge_block(self.constants):
                log.debug(f"challenge segment {idx}, starts at {curr.height} ")
                seg, height = await self._create_challenge_segment(curr, sub_epoch_n, header_blocks, blocks, first)
                if seg is None:
                    log.error(f"failed creating segment {curr.header_hash} ")
                    return
                segments.append(seg)
                idx += 1
                first = False
            else:
                height = height + uint32(1)
            curr = header_blocks[self.blockchain.height_to_hash(height)]
            if curr is None:
                return

        log.debug(f"next sub epoch starts at {height}")
        return segments

    async def get_prev_two_slots_height(self, se_start: BlockRecord) -> uint32:
        slot = 0
        batch_size = 50
        curr_rec = se_start
        blocks = await self.blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
        end = curr_rec.height
        while slot < 2:
            if curr_rec.height > 0:
                if curr_rec.first_in_sub_slot:
                    slot += 1
                else:
                    if end - curr_rec.height == batch_size - 1:
                        blocks = await self.blockchain.get_block_records_in_range(curr_rec.height - batch_size, curr_rec.height)
                        end = curr_rec.height
                    curr_rec = blocks[self.blockchain.height_to_hash(uint32(curr_rec.height - 1))]

        return curr_rec.height

    async def _create_challenge_segment(self, header_block: HeaderBlock, sub_epoch_n: uint32, header_blocks: Dict[(bytes32, HeaderBlock)], blocks: Dict[(bytes32, BlockRecord)], first_segment_in_sub_epoch: bool) -> Tuple[(Optional[SubEpochChallengeSegment], uint32)]:
        assert self.blockchain is not None
        sub_slots = []
        log.debug(f"create challenge segment block {header_block.header_hash} block height {header_block.height} ")
        first_sub_slots, first_rc_end_of_slot_vdf = await self._WeightProofHandler__first_sub_slot_vdfs(header_block, header_blocks, blocks, first_segment_in_sub_epoch)
        if first_sub_slots is None:
            log.error('failed building first sub slots')
            return (
             None, uint32(0))
        sub_slots.extend(first_sub_slots)
        ssd = await _challenge_block_vdfs(self.constants, header_block, blocks[header_block.header_hash], blocks)
        sub_slots.append(ssd)
        log.debug(f"create slot end vdf for block {header_block.header_hash} height {header_block.height} ")
        challenge_slot_end_sub_slots, end_height = await self._WeightProofHandler__slot_end_vdf(uint32(header_block.height + 1), header_blocks, blocks)
        if challenge_slot_end_sub_slots is None:
            log.error('failed building slot end ')
            return (
             None, uint32(0))
        sub_slots.extend(challenge_slot_end_sub_slots)
        if first_segment_in_sub_epoch:
            if sub_epoch_n != 0:
                return (
                 SubEpochChallengeSegment(sub_epoch_n, sub_slots, first_rc_end_of_slot_vdf),
                 end_height)
        return (SubEpochChallengeSegment(sub_epoch_n, sub_slots, None), end_height)

    async def __first_sub_slot_vdfs--- This code section failed: ---

 L. 375         0  LOAD_FAST                'blocks'
                2  LOAD_FAST                'header_block'
                4  LOAD_ATTR                header_hash
                6  BINARY_SUBSCR    
                8  STORE_FAST               'header_block_sub_rec'

 L. 377        10  LOAD_FAST                'header_block_sub_rec'
               12  STORE_FAST               'curr_sub_rec'

 L. 378        14  LOAD_CONST               None
               16  STORE_FAST               'first_rc_end_of_slot_vdf'

 L. 379        18  LOAD_FAST                'first_in_sub_epoch'
               20  POP_JUMP_IF_FALSE    70  'to 70'
               22  LOAD_FAST                'curr_sub_rec'
               24  LOAD_ATTR                height
               26  LOAD_CONST               0
               28  COMPARE_OP               >
               30  POP_JUMP_IF_FALSE    70  'to 70'

 L. 380        32  SETUP_LOOP           54  'to 54'
             34_0  COME_FROM            50  '50'
               34  LOAD_FAST                'curr_sub_rec'
               36  LOAD_ATTR                sub_epoch_summary_included
               38  POP_JUMP_IF_TRUE     52  'to 52'

 L. 381        40  LOAD_FAST                'blocks'
               42  LOAD_FAST                'curr_sub_rec'
               44  LOAD_ATTR                prev_hash
               46  BINARY_SUBSCR    
               48  STORE_FAST               'curr_sub_rec'
               50  JUMP_LOOP            34  'to 34'
             52_0  COME_FROM            38  '38'
               52  POP_BLOCK        
             54_0  COME_FROM_LOOP       32  '32'

 L. 382        54  LOAD_FAST                'self'
               56  LOAD_METHOD              first_rc_end_of_slot_vdf
               58  LOAD_FAST                'header_block'
               60  LOAD_FAST                'blocks'
               62  LOAD_FAST                'header_blocks'
               64  CALL_METHOD_3         3  '3 positional arguments'
               66  STORE_FAST               'first_rc_end_of_slot_vdf'
               68  JUMP_FORWARD        188  'to 188'
             70_0  COME_FROM            30  '30'
             70_1  COME_FROM            20  '20'

 L. 384        70  LOAD_FAST                'header_block_sub_rec'
               72  LOAD_ATTR                overflow
               74  POP_JUMP_IF_FALSE   156  'to 156'
               76  LOAD_FAST                'header_block_sub_rec'
               78  LOAD_ATTR                first_in_sub_slot
               80  POP_JUMP_IF_FALSE   156  'to 156'

 L. 385        82  LOAD_CONST               2
               84  STORE_FAST               'sub_slots_num'

 L. 386        86  SETUP_LOOP          188  'to 188'
             88_0  COME_FROM           150  '150'
               88  LOAD_FAST                'sub_slots_num'
               90  LOAD_CONST               0
               92  COMPARE_OP               >
               94  POP_JUMP_IF_FALSE   152  'to 152'
               96  LOAD_FAST                'curr_sub_rec'
               98  LOAD_ATTR                height
              100  LOAD_CONST               0
              102  COMPARE_OP               >
              104  POP_JUMP_IF_FALSE   152  'to 152'

 L. 387       106  LOAD_FAST                'curr_sub_rec'
              108  LOAD_ATTR                first_in_sub_slot
              110  POP_JUMP_IF_FALSE   140  'to 140'

 L. 388       112  LOAD_FAST                'curr_sub_rec'
              114  LOAD_ATTR                finished_challenge_slot_hashes
              116  LOAD_CONST               None
              118  COMPARE_OP               is-not
              120  POP_JUMP_IF_TRUE    126  'to 126'
              122  LOAD_ASSERT              AssertionError
              124  RAISE_VARARGS_1       1  'exception instance'
            126_0  COME_FROM           120  '120'

 L. 389       126  LOAD_FAST                'sub_slots_num'
              128  LOAD_GLOBAL              len
              130  LOAD_FAST                'curr_sub_rec'
              132  LOAD_ATTR                finished_challenge_slot_hashes
              134  CALL_FUNCTION_1       1  '1 positional argument'
              136  INPLACE_SUBTRACT 
              138  STORE_FAST               'sub_slots_num'
            140_0  COME_FROM           110  '110'

 L. 390       140  LOAD_FAST                'blocks'
              142  LOAD_FAST                'curr_sub_rec'
              144  LOAD_ATTR                prev_hash
              146  BINARY_SUBSCR    
              148  STORE_FAST               'curr_sub_rec'
              150  JUMP_LOOP            88  'to 88'
            152_0  COME_FROM           104  '104'
            152_1  COME_FROM            94  '94'
              152  POP_BLOCK        
              154  JUMP_FORWARD        188  'to 188'
            156_0  COME_FROM            80  '80'
            156_1  COME_FROM            74  '74'

 L. 392       156  SETUP_LOOP          188  'to 188'
            158_0  COME_FROM           184  '184'
              158  LOAD_FAST                'curr_sub_rec'
              160  LOAD_ATTR                first_in_sub_slot
              162  POP_JUMP_IF_TRUE    186  'to 186'
              164  LOAD_FAST                'curr_sub_rec'
              166  LOAD_ATTR                height
              168  LOAD_CONST               0
              170  COMPARE_OP               >
              172  POP_JUMP_IF_FALSE   186  'to 186'

 L. 393       174  LOAD_FAST                'blocks'
              176  LOAD_FAST                'curr_sub_rec'
              178  LOAD_ATTR                prev_hash
              180  BINARY_SUBSCR    
              182  STORE_FAST               'curr_sub_rec'
              184  JUMP_LOOP           158  'to 158'
            186_0  COME_FROM           172  '172'
            186_1  COME_FROM           162  '162'
              186  POP_BLOCK        
            188_0  COME_FROM_LOOP      156  '156'
            188_1  COME_FROM           154  '154'
            188_2  COME_FROM_LOOP       86  '86'
            188_3  COME_FROM            68  '68'

 L. 395       188  LOAD_FAST                'header_blocks'
              190  LOAD_FAST                'curr_sub_rec'
              192  LOAD_ATTR                header_hash
              194  BINARY_SUBSCR    
              196  STORE_FAST               'curr'

 L. 396       198  BUILD_LIST_0          0 
              200  STORE_FAST               'sub_slots_data'

 L. 397       202  BUILD_LIST_0          0 
              204  STORE_FAST               'tmp_sub_slots_data'

 L. 398       206  SETUP_LOOP          434  'to 434'
            208_0  COME_FROM           430  '430'
              208  LOAD_FAST                'curr'
              210  LOAD_ATTR                height
              212  LOAD_FAST                'header_block'
              214  LOAD_ATTR                height
              216  COMPARE_OP               <
          218_220  POP_JUMP_IF_FALSE   432  'to 432'

 L. 399       222  LOAD_FAST                'curr'
              224  LOAD_CONST               None
              226  COMPARE_OP               is
              228  POP_JUMP_IF_FALSE   244  'to 244'

 L. 400       230  LOAD_GLOBAL              log
              232  LOAD_METHOD              error
              234  LOAD_STR                 'failed fetching block'
              236  CALL_METHOD_1         1  '1 positional argument'
              238  POP_TOP          

 L. 401       240  LOAD_CONST               (None, None)
              242  RETURN_VALUE     
            244_0  COME_FROM           228  '228'

 L. 402       244  LOAD_FAST                'curr'
              246  LOAD_ATTR                first_in_sub_slot
          248_250  POP_JUMP_IF_FALSE   348  'to 348'

 L. 404       252  LOAD_GLOBAL              blue_boxed_end_of_slot
              254  LOAD_FAST                'curr'
              256  LOAD_ATTR                finished_sub_slots
              258  LOAD_CONST               0
              260  BINARY_SUBSCR    
              262  CALL_FUNCTION_1       1  '1 positional argument'
          264_266  POP_JUMP_IF_TRUE    278  'to 278'

 L. 405       268  LOAD_FAST                'sub_slots_data'
              270  LOAD_METHOD              extend
              272  LOAD_FAST                'tmp_sub_slots_data'
              274  CALL_METHOD_1         1  '1 positional argument'
              276  POP_TOP          
            278_0  COME_FROM           264  '264'

 L. 407       278  SETUP_LOOP          344  'to 344'
              280  LOAD_GLOBAL              enumerate
              282  LOAD_FAST                'curr'
              284  LOAD_ATTR                finished_sub_slots
              286  CALL_FUNCTION_1       1  '1 positional argument'
              288  GET_ITER         
            290_0  COME_FROM           338  '338'
              290  FOR_ITER            342  'to 342'
              292  UNPACK_SEQUENCE_2     2 
              294  STORE_FAST               'idx'
              296  STORE_FAST               'sub_slot'

 L. 408       298  LOAD_CONST               None
              300  STORE_FAST               'curr_icc_info'

 L. 409       302  LOAD_FAST                'sub_slot'
              304  LOAD_ATTR                infused_challenge_chain
              306  LOAD_CONST               None
              308  COMPARE_OP               is-not
          310_312  POP_JUMP_IF_FALSE   322  'to 322'

 L. 410       314  LOAD_FAST                'sub_slot'
              316  LOAD_ATTR                infused_challenge_chain
              318  LOAD_ATTR                infused_challenge_chain_end_of_slot_vdf
              320  STORE_FAST               'curr_icc_info'
            322_0  COME_FROM           310  '310'

 L. 411       322  LOAD_FAST                'sub_slots_data'
              324  LOAD_METHOD              append
              326  LOAD_GLOBAL              handle_finished_slots
              328  LOAD_FAST                'sub_slot'
              330  LOAD_FAST                'curr_icc_info'
              332  CALL_FUNCTION_2       2  '2 positional arguments'
              334  CALL_METHOD_1         1  '1 positional argument'
              336  POP_TOP          
          338_340  JUMP_LOOP           290  'to 290'
              342  POP_BLOCK        
            344_0  COME_FROM_LOOP      278  '278'

 L. 412       344  BUILD_LIST_0          0 
              346  STORE_FAST               'tmp_sub_slots_data'
            348_0  COME_FROM           248  '248'

 L. 413       348  LOAD_GLOBAL              SubSlotData

 L. 414       350  LOAD_CONST               None

 L. 415       352  LOAD_CONST               None

 L. 416       354  LOAD_CONST               None

 L. 417       356  LOAD_CONST               None

 L. 418       358  LOAD_CONST               None

 L. 419       360  LOAD_FAST                'curr'
              362  LOAD_ATTR                reward_chain_block
              364  LOAD_ATTR                signage_point_index

 L. 420       366  LOAD_CONST               None

 L. 421       368  LOAD_CONST               None

 L. 422       370  LOAD_CONST               None

 L. 423       372  LOAD_CONST               None

 L. 424       374  LOAD_FAST                'curr'
              376  LOAD_ATTR                reward_chain_block
              378  LOAD_ATTR                challenge_chain_ip_vdf

 L. 425       380  LOAD_FAST                'curr'
              382  LOAD_ATTR                reward_chain_block
              384  LOAD_ATTR                infused_challenge_chain_ip_vdf

 L. 426       386  LOAD_FAST                'curr'
              388  LOAD_ATTR                total_iters
              390  CALL_FUNCTION_13     13  '13 positional arguments'
              392  STORE_FAST               'ssd'

 L. 428       394  LOAD_FAST                'tmp_sub_slots_data'
              396  LOAD_METHOD              append
              398  LOAD_FAST                'ssd'
              400  CALL_METHOD_1         1  '1 positional argument'
              402  POP_TOP          

 L. 429       404  LOAD_FAST                'header_blocks'
              406  LOAD_FAST                'self'
              408  LOAD_ATTR                blockchain
              410  LOAD_METHOD              height_to_hash
              412  LOAD_GLOBAL              uint32
              414  LOAD_FAST                'curr'
              416  LOAD_ATTR                height
              418  LOAD_CONST               1
              420  BINARY_ADD       
              422  CALL_FUNCTION_1       1  '1 positional argument'
              424  CALL_METHOD_1         1  '1 positional argument'
              426  BINARY_SUBSCR    
              428  STORE_FAST               'curr'
              430  JUMP_LOOP           208  'to 208'
            432_0  COME_FROM           218  '218'
              432  POP_BLOCK        
            434_0  COME_FROM_LOOP      206  '206'

 L. 431       434  LOAD_GLOBAL              len
              436  LOAD_FAST                'tmp_sub_slots_data'
              438  CALL_FUNCTION_1       1  '1 positional argument'
              440  LOAD_CONST               0
              442  COMPARE_OP               >
          444_446  POP_JUMP_IF_FALSE   458  'to 458'

 L. 432       448  LOAD_FAST                'sub_slots_data'
              450  LOAD_METHOD              extend
              452  LOAD_FAST                'tmp_sub_slots_data'
              454  CALL_METHOD_1         1  '1 positional argument'
              456  POP_TOP          
            458_0  COME_FROM           444  '444'

 L. 434       458  SETUP_LOOP          524  'to 524'
              460  LOAD_GLOBAL              enumerate
              462  LOAD_FAST                'header_block'
              464  LOAD_ATTR                finished_sub_slots
              466  CALL_FUNCTION_1       1  '1 positional argument'
              468  GET_ITER         
            470_0  COME_FROM           518  '518'
              470  FOR_ITER            522  'to 522'
              472  UNPACK_SEQUENCE_2     2 
              474  STORE_FAST               'idx'
              476  STORE_FAST               'sub_slot'

 L. 435       478  LOAD_CONST               None
              480  STORE_FAST               'curr_icc_info'

 L. 436       482  LOAD_FAST                'sub_slot'
              484  LOAD_ATTR                infused_challenge_chain
              486  LOAD_CONST               None
              488  COMPARE_OP               is-not
          490_492  POP_JUMP_IF_FALSE   502  'to 502'

 L. 437       494  LOAD_FAST                'sub_slot'
              496  LOAD_ATTR                infused_challenge_chain
              498  LOAD_ATTR                infused_challenge_chain_end_of_slot_vdf
              500  STORE_FAST               'curr_icc_info'
            502_0  COME_FROM           490  '490'

 L. 438       502  LOAD_FAST                'sub_slots_data'
              504  LOAD_METHOD              append
              506  LOAD_GLOBAL              handle_finished_slots
              508  LOAD_FAST                'sub_slot'
              510  LOAD_FAST                'curr_icc_info'
              512  CALL_FUNCTION_2       2  '2 positional arguments'
              514  CALL_METHOD_1         1  '1 positional argument'
              516  POP_TOP          
          518_520  JUMP_LOOP           470  'to 470'
              522  POP_BLOCK        
            524_0  COME_FROM_LOOP      458  '458'

 L. 440       524  LOAD_FAST                'sub_slots_data'
              526  LOAD_FAST                'first_rc_end_of_slot_vdf'
              528  BUILD_TUPLE_2         2 
              530  RETURN_VALUE     
               -1  RETURN_LAST      

Parse error at or near `JUMP_FORWARD' instruction at offset 154

    def first_rc_end_of_slot_vdf(self, header_block, blocks: Dict[(bytes32, BlockRecord)], header_blocks: Dict[(bytes32, HeaderBlock)]) -> Optional[VDFInfo]:
        curr = blocks[header_block.header_hash]
        while curr.height > 0:
            if not curr.sub_epoch_summary_included:
                curr = blocks[curr.prev_hash]

        return header_blocks[curr.header_hash].finished_sub_slots[-1].reward_chain.end_of_slot_vdf

    async def __slot_end_vdf(self, start_height: uint32, header_blocks: Dict[(bytes32, HeaderBlock)], blocks: Dict[(bytes32, BlockRecord)]) -> Tuple[(Optional[List[SubSlotData]], uint32)]:
        log.debug(f"slot end vdf start height {start_height}")
        curr = header_blocks[self.blockchain.height_to_hash(start_height)]
        curr_header_hash = curr.header_hash
        sub_slots_data = []
        tmp_sub_slots_data = []
        while not blocks[curr_header_hash].is_challenge_block(self.constants):
            if curr.first_in_sub_slot:
                sub_slots_data.extend(tmp_sub_slots_data)
                curr_prev_header_hash = curr.prev_header_hash
                for idx, sub_slot in enumerate(curr.finished_sub_slots):
                    prev_rec = blocks[curr_prev_header_hash]
                    eos_vdf_iters = prev_rec.sub_slot_iters
                    if idx == 0:
                        eos_vdf_iters = uint64(prev_rec.sub_slot_iters - prev_rec.ip_iters(self.constants))
                    else:
                        sub_slots_data.append(handle_end_of_slot(sub_slot, eos_vdf_iters))

                tmp_sub_slots_data = []
            else:
                tmp_sub_slots_data.append(self.handle_block_vdfs(curr, blocks))
                curr = header_blocks[self.blockchain.height_to_hash(uint32(curr.height + 1))]
                curr_header_hash = curr.header_hash

        if len(tmp_sub_slots_data) > 0:
            sub_slots_data.extend(tmp_sub_slots_data)
        log.debug(f"slot end vdf end height {curr.height} slots {len(sub_slots_data)} ")
        return (
         sub_slots_data, curr.height)

    def handle_block_vdfs(self, curr: HeaderBlock, blocks: Dict[(bytes32, BlockRecord)]):
        cc_sp_proof = None
        icc_ip_proof = None
        cc_sp_info = None
        icc_ip_info = None
        block_record = blocks[curr.header_hash]
        if curr.infused_challenge_chain_ip_proof is not None:
            assert curr.reward_chain_block.infused_challenge_chain_ip_vdf
            icc_ip_proof = curr.infused_challenge_chain_ip_proof
            icc_ip_info = curr.reward_chain_block.infused_challenge_chain_ip_vdf
        if curr.challenge_chain_sp_proof is not None:
            assert curr.reward_chain_block.challenge_chain_sp_vdf
            cc_sp_vdf_info = curr.reward_chain_block.challenge_chain_sp_vdf
            if not curr.challenge_chain_sp_proof.normalized_to_identity:
                _, _, _, _, cc_vdf_iters, _ = get_signage_point_vdf_info(self.constants, curr.finished_sub_slots, block_record.overflow, None if curr.height == 0 else blocks[curr.prev_header_hash], BlockCache(blocks), block_record.sp_total_iters(self.constants), block_record.sp_iters(self.constants))
                cc_sp_vdf_info = VDFInfo(curr.reward_chain_block.challenge_chain_sp_vdf.challenge, cc_vdf_iters, curr.reward_chain_block.challenge_chain_sp_vdf.output)
            cc_sp_proof = curr.challenge_chain_sp_proof
            cc_sp_info = cc_sp_vdf_info
        return SubSlotDataNonecc_sp_proofcurr.challenge_chain_ip_prooficc_ip_proofcc_sp_infocurr.reward_chain_block.signage_point_indexNoneNoneNoneNonecurr.reward_chain_block.challenge_chain_ip_vdficc_ip_infocurr.total_iters

    def validate_weight_proof_single_proc(self, weight_proof: WeightProof) -> Tuple[(bool, uint32)]:
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return (False, uint32(0))
        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning('weight proof failed sub epoch data validation')
            return (
             False, uint32(0))
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(self.constants, summaries, weight_proof)
        log.info('validate sub epoch challenge segments')
        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error('failed weight proof sub epoch sample validation')
            return (
             False, uint32(0))
        if not _validate_sub_epoch_segments(constants, rng, wp_segment_bytes, summary_bytes):
            return (False, uint32(0))
        log.info('validate weight proof recent blocks')
        if not _validate_recent_blocks(constants, wp_recent_chain_bytes, summary_bytes):
            return (False, uint32(0))
        return (True, self.get_fork_point(summaries))

    def get_fork_point_no_validations(self, weight_proof: WeightProof) -> Tuple[(bool, uint32)]:
        log.debug('get fork point skip validations')
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return (False, uint32(0))
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning('weight proof failed to validate sub epoch summaries')
            return (
             False, uint32(0))
        return (True, self.get_fork_point(summaries))

    async def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[(bool, uint32, List[SubEpochSummary])]:
        assert self.blockchain is not None
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return (False, uint32(0), [])
        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.error('weight proof failed sub epoch data validation')
            return (
             False, uint32(0), [])
        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error('failed weight proof sub epoch sample validation')
            return (
             False, uint32(0), [])
        executor = ProcessPoolExecutor(1)
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(self.constants, summaries, weight_proof)
        segment_validation_task = asyncio.get_running_loop().run_in_executor(executor, _validate_sub_epoch_segments, constants, rng, wp_segment_bytes, summary_bytes)
        recent_blocks_validation_task = asyncio.get_running_loop().run_in_executor(executor, _validate_recent_blocks, constants, wp_recent_chain_bytes, summary_bytes)
        valid_segment_task = segment_validation_task
        valid_recent_blocks_task = recent_blocks_validation_task
        valid_recent_blocks = await valid_recent_blocks_task
        if not valid_recent_blocks:
            log.error('failed validating weight proof recent blocks')
            return (
             False, uint32(0), [])
        valid_segments = await valid_segment_task
        if not valid_segments:
            log.error('failed validating weight proof sub epoch segments')
            return (
             False, uint32(0), [])
        return (
         True, self.get_fork_point(summaries), summaries)

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        fork_point_index = 0
        ses_heights = self.blockchain.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            log.debug(f"check summary {idx} height {summary_height}")
            local_ses = self.blockchain.get_ses(summary_height)
            if idx == len(received_summaries) - 1:
                break
            if local_ses is None or local_ses.get_hash() != received_summaries[idx].get_hash():
                break
            else:
                fork_point_index = idx

        if fork_point_index > 2:
            height = ses_heights[fork_point_index - 2]
        else:
            height = uint32(0)
        return height


def _get_weights_for_sampling(rng: random.Random, total_weight: uint128, recent_chain: List[HeaderBlock]) -> Optional[List[uint128]]:
    weight_to_check = []
    last_l_weight = recent_chain[-1].reward_chain_block.weight - recent_chain[0].reward_chain_block.weight
    delta = last_l_weight / total_weight
    prob_of_adv_succeeding = 1 - math.log(WeightProofHandler.C, delta)
    if prob_of_adv_succeeding <= 0:
        return
    queries = -WeightProofHandler.LAMBDA_L * math.log(2, prob_of_adv_succeeding)
    for i in range(int(queries) + 1):
        u = rng.random()
        q = 1 - delta ** u
        weight = q * float(total_weight)
        weight_to_check.append(uint128(int(weight)))

    weight_to_check.sort()
    return weight_to_check


def _sample_sub_epoch(start_of_epoch_weight: uint128, end_of_epoch_weight: uint128, weight_to_check: List[uint128]) -> bool:
    """
    weight_to_check: List[uint128] is expected to be sorted
    """
    if weight_to_check is None:
        return True
    if weight_to_check[-1] < start_of_epoch_weight:
        return False
    if weight_to_check[0] > end_of_epoch_weight:
        return False
    choose = False
    for weight in weight_to_check:
        if weight > end_of_epoch_weight:
            return False
        if start_of_epoch_weight< weight < end_of_epoch_weight:
            log.debug(f"start weight: {start_of_epoch_weight}")
            log.debug(f"weight to check {weight}")
            log.debug(f"end weight: {end_of_epoch_weight}")
            choose = True
            break

    return choose


def _create_sub_epoch_data(sub_epoch_summary: SubEpochSummary) -> SubEpochData:
    reward_chain_hash = sub_epoch_summary.reward_chain_hash
    previous_sub_epoch_overflows = sub_epoch_summary.num_blocks_overflow
    sub_slot_iters = sub_epoch_summary.new_sub_slot_iters
    new_difficulty = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


async def _challenge_block_vdfs(constants: ConsensusConstants, header_block: HeaderBlock, block_rec: BlockRecord, sub_blocks: Dict[(bytes32, BlockRecord)]):
    _, _, _, _, cc_vdf_iters, _ = get_signage_point_vdf_info(constants, header_block.finished_sub_slots, block_rec.overflow, None if header_block.height == 0 else sub_blocks[header_block.prev_header_hash], BlockCache(sub_blocks), block_rec.sp_total_iters(constants), block_rec.sp_iters(constants))
    cc_sp_info = None
    if header_block.reward_chain_block.challenge_chain_sp_vdf:
        cc_sp_info = header_block.reward_chain_block.challenge_chain_sp_vdf
        assert header_block.challenge_chain_sp_proof
        if not header_block.challenge_chain_sp_proof.normalized_to_identity:
            cc_sp_info = VDFInfo(header_block.reward_chain_block.challenge_chain_sp_vdf.challenge, cc_vdf_iters, header_block.reward_chain_block.challenge_chain_sp_vdf.output)
        ssd = SubSlotDataheader_block.reward_chain_block.proof_of_spaceheader_block.challenge_chain_sp_proofheader_block.challenge_chain_ip_proofNonecc_sp_infoheader_block.reward_chain_block.signage_point_indexNoneNoneNoneNoneheader_block.reward_chain_block.challenge_chain_ip_vdfheader_block.reward_chain_block.infused_challenge_chain_ip_vdfblock_rec.total_iters
        return ssd


def handle_finished_slots(end_of_slot: EndOfSubSlotBundle, icc_end_of_slot_info):
    return SubSlotDataNoneNoneNoneNoneNoneNone(None if end_of_slot.proofs.challenge_chain_slot_proof is None else end_of_slot.proofs.challenge_chain_slot_proof)(None if end_of_slot.proofs.infused_challenge_chain_slot_proof is None else end_of_slot.proofs.infused_challenge_chain_slot_proof)end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdficc_end_of_slot_infoNoneNoneNone


def handle_end_of_slot(sub_slot: EndOfSubSlotBundle, eos_vdf_iters: uint64):
    assert sub_slot.infused_challenge_chain
    assert sub_slot.proofs.infused_challenge_chain_slot_proof
    if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
        icc_info = sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    else:
        icc_info = VDFInfo(sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.challenge, eos_vdf_iters, sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output)
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        cc_info = sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf
    else:
        cc_info = VDFInfo(sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge, eos_vdf_iters, sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.output)
    assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
    return SubSlotDataNoneNoneNoneNoneNoneNonesub_slot.proofs.challenge_chain_slot_proofsub_slot.proofs.infused_challenge_chain_slot_proofcc_infoicc_infoNoneNoneNone


def compress_segments(full_segment_index, segments: List[SubEpochChallengeSegment]) -> List[SubEpochChallengeSegment]:
    compressed_segments = []
    compressed_segments.append(segments[0])
    for idx, segment in enumerate(segments[1:]):
        if idx != full_segment_index:
            segment = compress_segment(segment)
        else:
            compressed_segments.append(segment)

    return compressed_segments


def compress_segment(segment: SubEpochChallengeSegment) -> SubEpochChallengeSegment:
    comp_seg = SubEpochChallengeSegment(segment.sub_epoch_n, [], segment.rc_slot_end_info)
    for slot in segment.sub_slots:
        comp_seg.sub_slots.append(slot)
        if slot.is_challenge():
            break

    return segment


def _validate_sub_epoch_summaries(constants: ConsensusConstants, weight_proof: WeightProof) -> Tuple[(Optional[List[SubEpochSummary]], Optional[List[uint128]])]:
    last_ses_hash, last_ses_sub_height = _get_last_ses_hash(constants, weight_proof.recent_chain_data)
    if last_ses_hash is None:
        log.warning('could not find last ses block')
        return (None, None)
    summaries, total, sub_epoch_weight_list = _map_sub_epoch_summaries(constants.SUB_EPOCH_BLOCKS, constants.GENESIS_CHALLENGE, weight_proof.sub_epochs, constants.DIFFICULTY_STARTING)
    log.info(f"validating {len(summaries)} sub epochs")
    if not _validate_summaries_weight(constants, total, summaries, weight_proof):
        log.error('failed validating weight')
        return (None, None)
    last_ses = summaries[-1]
    log.debug(f"last ses sub height {last_ses_sub_height}")
    if last_ses.get_hash() != last_ses_hash:
        log.error(f"failed to validate ses hashes block height {last_ses_sub_height}")
        return (None, None)
    return (
     summaries, sub_epoch_weight_list)


def _map_sub_epoch_summaries(sub_blocks_for_se: uint32, ses_hash: bytes32, sub_epoch_data: List[SubEpochData], curr_difficulty: uint64) -> Tuple[(List[SubEpochSummary], uint128, List[uint128])]:
    total_weight = uint128(0)
    summaries = []
    sub_epoch_weight_list = []
    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(ses_hash, data.reward_chain_hash, data.num_blocks_overflow, data.new_difficulty, data.new_sub_slot_iters)
        if idx < len(sub_epoch_data) - 1:
            delta = 0
            if idx > 0:
                delta = sub_epoch_data[idx].num_blocks_overflow
            log.debug(f"sub epoch {idx} start weight is {total_weight + curr_difficulty} ")
            sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
            total_weight = total_weight + uint128(curr_difficulty * (sub_blocks_for_se + sub_epoch_data[idx + 1].num_blocks_overflow - delta))
        else:
            if data.new_difficulty is not None:
                curr_difficulty = data.new_difficulty
            summaries.append(ses)
            ses_hash = std_hash(ses)

    sub_epoch_weight_list.append(uint128(total_weight + curr_difficulty))
    return (
     summaries, total_weight, sub_epoch_weight_list)


def _validate_summaries_weight(constants: ConsensusConstants, sub_epoch_data_weight, summaries, weight_proof) -> bool:
    num_over = summaries[-1].num_blocks_overflow
    ses_end_height = (len(summaries) - 1) * constants.SUB_EPOCH_BLOCKS + num_over - 1
    curr = None
    for block in weight_proof.recent_chain_data:
        if block.reward_chain_block.height == ses_end_height:
            curr = block

    if curr is None:
        return False
    return curr.reward_chain_block.weight == sub_epoch_data_weight


def _validate_sub_epoch_segments(constants_dict: Dict, rng: random.Random, weight_proof_bytes: bytes, summaries_bytes: List[bytes]):
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    sub_epoch_segments = SubEpochSegments.from_bytes(weight_proof_bytes)
    rc_sub_slot_hash = constants.GENESIS_CHALLENGE
    total_blocks, total_ip_iters = (0, 0)
    total_slot_iters, total_slots = (0, 0)
    total_ip_iters = 0
    prev_ses = None
    segments_by_sub_epoch = map_segments_by_sub_epoch(sub_epoch_segments.challenge_segments)
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    for sub_epoch_n, segments in segments_by_sub_epoch.items():
        prev_ssi = curr_ssi
        curr_difficulty, curr_ssi = _get_curr_diff_ssi(constants, sub_epoch_n, summaries)
        log.debug(f"validate sub epoch {sub_epoch_n}")
        sampled_seg_index = rng.choice(range(len(segments)))
        if sub_epoch_n > 0:
            rc_sub_slot = __get_rc_sub_slot(constants, segments[0], summaries, curr_ssi)
            prev_ses = summaries[sub_epoch_n - 1]
            rc_sub_slot_hash = rc_sub_slot.get_hash()
        else:
            if not summaries[sub_epoch_n].reward_chain_hash == rc_sub_slot_hash:
                log.error(f"failed reward_chain_hash validation sub_epoch {sub_epoch_n}")
                return False
            for idx, segment in enumerate(segments):
                valid_segment, ip_iters, slot_iters, slots = _validate_segment(constants, segment, curr_ssi, prev_ssi, curr_difficulty, prev_ses, idx == 0, sampled_seg_index == idx)
                if not valid_segment:
                    log.error(f"failed to validate sub_epoch {segment.sub_epoch_n} segment {idx} slots")
                    return False
                else:
                    prev_ses = None
                    total_blocks += 1
                    total_slot_iters += slot_iters
                    total_slots += slots
                    total_ip_iters += ip_iters

    return True


def _validate_segment(constants: ConsensusConstants, segment: SubEpochChallengeSegment, curr_ssi: uint64, prev_ssi: uint64, curr_difficulty: uint64, ses: Optional[SubEpochSummary], first_segment_in_se: bool, sampled: bool) -> Tuple[(bool, int, int, int)]:
    ip_iters, slot_iters, slots = (0, 0, 0)
    after_challenge = False
    for idx, sub_slot_data in enumerate(segment.sub_slots):
        if sampled and sub_slot_data.is_challenge():
            after_challenge = True
            required_iters = __validate_pospace(constants, segment, idx, curr_difficulty, ses, first_segment_in_se)
            if required_iters is None:
                return (False, uint64(0), uint64(0), uint64(0))
            assert sub_slot_data.signage_point_index is not None
            ip_iters = ip_iters + calculate_ip_iters(constants, curr_ssi, sub_slot_data.signage_point_index, required_iters)
            if not _validate_challenge_block_vdfs(constants, idx, segment.sub_slots, curr_ssi):
                log.error(f"failed to validate challenge slot {idx} vdfs")
                return (
                 False, uint64(0), uint64(0), uint64(0))
        else:
            pass
        if sampled:
            if after_challenge:
                if not _validate_sub_slot_data(constants, idx, segment.sub_slots, curr_ssi):
                    log.error(f"failed to validate sub slot data {idx} vdfs")
                    return (
                     False, uint64(0), uint64(0), uint64(0))
                slot_iters = slot_iters + curr_ssi
                slots = slots + uint64(1)

    return (
     True, ip_iters, slot_iters, slots)


def _validate_challenge_block_vdfs(constants: ConsensusConstants, sub_slot_idx: int, sub_slots: List[SubSlotData], ssi: uint64) -> bool:
    sub_slot_data = sub_slots[sub_slot_idx]
    if sub_slot_data.cc_signage_point is not None:
        if sub_slot_data.cc_sp_vdf_info:
            assert sub_slot_data.signage_point_index
            sp_input = ClassgroupElement.get_default_element()
            if not sub_slot_data.cc_signage_point.normalized_to_identity:
                if sub_slot_idx >= 1:
                    is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
                    prev_ssd = sub_slots[sub_slot_idx - 1]
                    sp_input = sub_slot_data_vdf_input(constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi)
            if not sub_slot_data.cc_signage_point.is_valid(constants, sp_input, sub_slot_data.cc_sp_vdf_info):
                log.error(f"failed to validate challenge chain signage point 2 {sub_slot_data.cc_sp_vdf_info}")
                return False
            assert sub_slot_data.cc_infusion_point
            assert sub_slot_data.cc_ip_vdf_info
            ip_input = ClassgroupElement.get_default_element()
            cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
            if not sub_slot_data.cc_infusion_point.normalized_to_identity:
                if sub_slot_idx >= 1:
                    prev_ssd = sub_slots[sub_slot_idx - 1]
                    if prev_ssd.cc_slot_end is None:
                        assert prev_ssd.cc_ip_vdf_info
                        assert prev_ssd.total_iters
                        assert sub_slot_data.total_iters
                        ip_input = prev_ssd.cc_ip_vdf_info.output
                        ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
                        cc_ip_vdf_info = VDFInfo(sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output)
            if not sub_slot_data.cc_infusion_point.is_valid(constants, ip_input, cc_ip_vdf_info):
                log.error(f"failed to validate challenge chain infusion point {sub_slot_data.cc_ip_vdf_info}")
                return False
        return True


def _validate_sub_slot_data(constants: ConsensusConstants, sub_slot_idx: int, sub_slots: List[SubSlotData], ssi: uint64) -> bool:
    sub_slot_data = sub_slots[sub_slot_idx]
    assert sub_slot_idx > 0
    prev_ssd = sub_slots[sub_slot_idx - 1]
    if sub_slot_data.is_end_of_slot():
        if sub_slot_data.icc_slot_end is not None:
            input = ClassgroupElement.get_default_element()
            if not sub_slot_data.icc_slot_end.normalized_to_identity:
                if prev_ssd.icc_ip_vdf_info is not None:
                    assert prev_ssd.icc_ip_vdf_info
                    input = prev_ssd.icc_ip_vdf_info.output
            assert sub_slot_data.icc_slot_end_info
            if not sub_slot_data.icc_slot_end.is_valid(constants, input, sub_slot_data.icc_slot_end_info, None):
                log.error(f"failed icc slot end validation  {sub_slot_data.icc_slot_end_info} ")
                return False
            assert sub_slot_data.cc_slot_end_info
            assert sub_slot_data.cc_slot_end
            input = ClassgroupElement.get_default_element()
            if not prev_ssd.is_end_of_slot():
                if not sub_slot_data.cc_slot_end.normalized_to_identity:
                    assert prev_ssd.cc_ip_vdf_info
                    input = prev_ssd.cc_ip_vdf_info.output
            if not sub_slot_data.cc_slot_end.is_valid(constants, input, sub_slot_data.cc_slot_end_info):
                log.error(f"failed cc slot end validation  {sub_slot_data.cc_slot_end_info}")
                return False
    else:
        idx = sub_slot_idx
        while idx < len(sub_slots) - 1:
            curr_slot = sub_slots[idx]
            if curr_slot.is_end_of_slot():
                if not curr_slot.cc_slot_end:
                    raise AssertionError
                elif curr_slot.cc_slot_end.normalized_to_identity is True:
                    log.debug(f"skip intermediate vdfs slot {sub_slot_idx}")
                    return True
                break
            else:
                idx += 1

    if sub_slot_data.icc_infusion_point is not None:
        if sub_slot_data.icc_ip_vdf_info is not None:
            input = ClassgroupElement.get_default_element()
            if not prev_ssd.is_challenge():
                if prev_ssd.icc_ip_vdf_info is not None:
                    input = prev_ssd.icc_ip_vdf_info.output
            if not sub_slot_data.icc_infusion_point.is_valid(constants, input, sub_slot_data.icc_ip_vdf_info, None):
                log.error(f"failed icc infusion point vdf validation  {sub_slot_data.icc_slot_end_info} ")
                return False
            assert sub_slot_data.signage_point_index is not None
            if sub_slot_data.cc_signage_point:
                assert sub_slot_data.cc_sp_vdf_info
                input = ClassgroupElement.get_default_element()
                if not sub_slot_data.cc_signage_point.normalized_to_identity:
                    is_overflow = is_overflow_block(constants, sub_slot_data.signage_point_index)
                    input = sub_slot_data_vdf_input(constants, sub_slot_data, sub_slot_idx, sub_slots, is_overflow, prev_ssd.is_end_of_slot(), ssi)
                if not sub_slot_data.cc_signage_point.is_valid(constants, input, sub_slot_data.cc_sp_vdf_info):
                    log.error(f"failed cc signage point vdf validation  {sub_slot_data.cc_sp_vdf_info}")
                    return False
                input = ClassgroupElement.get_default_element()
                assert sub_slot_data.cc_ip_vdf_info
                if not sub_slot_data.cc_infusion_point:
                    raise AssertionError
            cc_ip_vdf_info = sub_slot_data.cc_ip_vdf_info
            if not sub_slot_data.cc_infusion_point.normalized_to_identity:
                if prev_ssd.cc_slot_end is None:
                    assert prev_ssd.cc_ip_vdf_info
                    input = prev_ssd.cc_ip_vdf_info.output
                    assert sub_slot_data.total_iters
                    assert prev_ssd.total_iters
                    ip_vdf_iters = uint64(sub_slot_data.total_iters - prev_ssd.total_iters)
                    cc_ip_vdf_info = VDFInfo(sub_slot_data.cc_ip_vdf_info.challenge, ip_vdf_iters, sub_slot_data.cc_ip_vdf_info.output)
        if not sub_slot_data.cc_infusion_point.is_valid(constants, input, cc_ip_vdf_info):
            log.error(f"failed cc infusion point vdf validation  {sub_slot_data.cc_slot_end_info}")
            return False
        return True


def sub_slot_data_vdf_input(constants: ConsensusConstants, sub_slot_data: SubSlotData, sub_slot_idx: int, sub_slots: List[SubSlotData], is_overflow: bool, new_sub_slot: bool, ssi: uint64) -> ClassgroupElement:
    cc_input = ClassgroupElement.get_default_element()
    sp_total_iters = get_sp_total_iters(constants, is_overflow, ssi, sub_slot_data)
    ssd = None
    if is_overflow:
        if new_sub_slot:
            if sub_slot_idx >= 2:
                if sub_slots[sub_slot_idx - 2].cc_slot_end_info is None:
                    for ssd_idx in reversed(range(0, sub_slot_idx - 1)):
                        ssd = sub_slots[ssd_idx]
                        if ssd.cc_slot_end_info is not None:
                            ssd = sub_slots[ssd_idx + 1]
                            break
                        if not ssd.total_iters > sp_total_iters:
                            break

                    if ssd:
                        if ssd.cc_ip_vdf_info is not None:
                            if ssd.total_iters < sp_total_iters:
                                cc_input = ssd.cc_ip_vdf_info.output
            return cc_input
    if not is_overflow:
        if not new_sub_slot:
            for ssd_idx in reversed(range(0, sub_slot_idx)):
                ssd = sub_slots[ssd_idx]
                if ssd.cc_slot_end_info is not None:
                    ssd = sub_slots[ssd_idx + 1]
                    break
                if not ssd.total_iters > sp_total_iters:
                    break

            assert ssd is not None
            if ssd.cc_ip_vdf_info is not None:
                if ssd.total_iters < sp_total_iters:
                    cc_input = ssd.cc_ip_vdf_info.output
            return cc_input
        if not new_sub_slot:
            if is_overflow:
                slots_seen = 0
                for ssd_idx in reversed(range(0, sub_slot_idx)):
                    ssd = sub_slots[ssd_idx]
                    if ssd.cc_slot_end_info is not None:
                        slots_seen += 1
                        if slots_seen == 2:
                            return ClassgroupElement.get_default_element()
                    if ssd.cc_slot_end_info is None:
                        if not ssd.total_iters > sp_total_iters:
                            break

                assert ssd is not None
                if ssd.cc_ip_vdf_info is not None:
                    if ssd.total_iters < sp_total_iters:
                        cc_input = ssd.cc_ip_vdf_info.output
        return cc_input


def _validate_recent_blocks(constants_dict: Dict, recent_chain_bytes: bytes, summaries_bytes: List[bytes]) -> bool:
    constants, summaries = bytes_to_vars(constants_dict, summaries_bytes)
    recent_chain = RecentChainData.from_bytes(recent_chain_bytes)
    sub_blocks = BlockCache({})
    first_ses_idx = _get_ses_idx(recent_chain.recent_chain_data)
    ses_idx = len(summaries) - len(first_ses_idx)
    ssi = constants.SUB_SLOT_ITERS_STARTING
    diff = constants.DIFFICULTY_STARTING
    last_blocks_to_validate = 100
    for summary in summaries[:ses_idx]:
        if summary.new_sub_slot_iters is not None:
            ssi = summary.new_sub_slot_iters
        if summary.new_difficulty is not None:
            diff = summary.new_difficulty

    ses_blocks, sub_slots, transaction_blocks = (0, 0, 0)
    challenge, prev_challenge = (None, None)
    tip_height = recent_chain.recent_chain_data[-1].height
    prev_block_record = None
    deficit = uint8(0)
    for idx, block in enumerate(recent_chain.recent_chain_data):
        required_iters = uint64(0)
        overflow = False
        ses = False
        height = block.height
        for sub_slot in block.finished_sub_slots:
            prev_challenge = challenge
            challenge = sub_slot.challenge_chain.get_hash()
            deficit = sub_slot.reward_chain.deficit
            if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                ses = True
                assert summaries[ses_idx].get_hash() == sub_slot.challenge_chain.subepoch_summary_hash
                ses_idx += 1
            if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                ssi = sub_slot.challenge_chain.new_sub_slot_iters
            if sub_slot.challenge_chain.new_difficulty is not None:
                diff = sub_slot.challenge_chain.new_difficulty

        if challenge is not None:
            if prev_challenge is not None:
                overflow = is_overflow_block(constants, block.reward_chain_block.signage_point_index)
                deficit = get_deficit(constants, deficit, prev_block_record, overflow, len(block.finished_sub_slots))
                log.debug(f"wp, validate block {block.height}")
                if sub_slots > 2 and transaction_blocks > 11 and tip_height - block.height < last_blocks_to_validate:
                    required_iters, error = validate_finished_header_block(constants, sub_blocks, block, False, diff, ssi, ses_blocks > 2)
                    if error is not None:
                        log.error(f"block {block.header_hash} failed validation {error}")
                        return False
                else:
                    required_iters = _validate_pospace_recent_chain(constants, block, challenge, diff, overflow, prev_challenge)
                    if required_iters is None:
                        return False
        curr_block_ses = None if (not ses) else (summaries[ses_idx - 1])
        block_record = header_block_to_sub_block_record(constants, required_iters, block, ssi, overflow, deficit, height, curr_block_ses)
        log.debug(f"add block {block_record.height} to tmp sub blocks")
        sub_blocks.add_block_record(block_record)
        if block.first_in_sub_slot:
            sub_slots += 1
        else:
            if block.is_transaction_block:
                transaction_blocks += 1
            if ses:
                ses_blocks += 1
            prev_block_record = block_record

    return True


def _validate_pospace_recent_chain(constants, block, challenge, diff, overflow, prev_challenge):
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        cc_sp_hash = challenge
    else:
        cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    assert cc_sp_hash is not None
    q_str = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(constants, challenge if (not overflow) else prev_challenge, cc_sp_hash)
    if q_str is None:
        log.error(f"could not verify proof of space block {block.height} {overflow}")
        return
    required_iters = calculate_iterations_quality(constants.DIFFICULTY_CONSTANT_FACTOR, q_str, block.reward_chain_block.proof_of_space.size, diff, cc_sp_hash)
    return required_iters


def __validate_pospace(constants: ConsensusConstants, segment: SubEpochChallengeSegment, idx: int, curr_diff: uint64, ses: Optional[SubEpochSummary], first_in_sub_epoch: bool) -> Optional[uint64]:
    if first_in_sub_epoch and segment.sub_epoch_n == 0 and idx == 0:
        cc_sub_slot_hash = constants.GENESIS_CHALLENGE
    else:
        cc_sub_slot_hash = __get_cc_sub_slot(segment.sub_slots, idx, ses).get_hash()
    sub_slot_data = segment.sub_slots[idx]
    if sub_slot_data.signage_point_index and is_overflow_block(constants, sub_slot_data.signage_point_index):
        curr_slot = segment.sub_slots[idx - 1]
        assert curr_slot.cc_slot_end_info
        challenge = curr_slot.cc_slot_end_info.challenge
    else:
        challenge = cc_sub_slot_hash
    if sub_slot_data.cc_sp_vdf_info is None:
        cc_sp_hash = cc_sub_slot_hash
    else:
        cc_sp_hash = sub_slot_data.cc_sp_vdf_info.output.get_hash()
    assert sub_slot_data.proof_of_space is not None
    q_str = sub_slot_data.proof_of_space.verify_and_get_quality_string(constants, challenge, cc_sp_hash)
    if q_str is None:
        log.error('could not verify proof of space')
        return
    return calculate_iterations_quality(constants.DIFFICULTY_CONSTANT_FACTOR, q_str, sub_slot_data.proof_of_space.size, curr_diff, cc_sp_hash)


def __get_rc_sub_slot(constants: ConsensusConstants, segment: SubEpochChallengeSegment, summaries: List[SubEpochSummary], curr_ssi: uint64) -> RewardChainSubSlot:
    ses = summaries[uint32(segment.sub_epoch_n - 1)]
    first_idx = None
    first = None
    for idx, curr in enumerate(segment.sub_slots):
        if curr.cc_slot_end is None:
            first_idx = idx
            first = curr
            break

    assert first_idx
    idx = first_idx
    slots = segment.sub_slots
    slots_n = 1
    assert first
    assert first.signage_point_index is not None
    if is_overflow_block(constants, first.signage_point_index):
        if idx >= 2:
            if slots[idx - 2].cc_slot_end is None:
                slots_n = 2
    new_diff = None if ses is None else ses.new_difficulty
    new_ssi = None if ses is None else ses.new_sub_slot_iters
    ses_hash = None if ses is None else ses.get_hash()
    overflow = is_overflow_block(constants, first.signage_point_index)
    if overflow:
        if idx >= 2:
            if slots[idx - 2].cc_slot_end is not None:
                if slots[idx - 1].cc_slot_end is not None:
                    ses_hash = None
                    new_ssi = None
                    new_diff = None
    sub_slot = slots[idx]
    while True:
        if sub_slot.cc_slot_end:
            slots_n -= 1
            if slots_n == 0:
                break
        idx -= 1
        sub_slot = slots[idx]

    icc_sub_slot_hash = None
    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None
    assert segment.rc_slot_end_info is not None
    if idx != 0:
        cc_vdf_info = VDFInfo(sub_slot.cc_slot_end_info.challenge, curr_ssi, sub_slot.cc_slot_end_info.output)
        if sub_slot.icc_slot_end_info is not None:
            icc_slot_end_info = VDFInfo(sub_slot.icc_slot_end_info.challenge, curr_ssi, sub_slot.icc_slot_end_info.output)
            icc_sub_slot_hash = icc_slot_end_info.get_hash()
    else:
        cc_vdf_info = sub_slot.cc_slot_end_info
        if sub_slot.icc_slot_end_info is not None:
            icc_sub_slot_hash = sub_slot.icc_slot_end_info.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(cc_vdf_info, icc_sub_slot_hash, ses_hash, new_ssi, new_diff)
    rc_sub_slot = RewardChainSubSlot(segment.rc_slot_end_info, cc_sub_slot.get_hash(), icc_sub_slot_hash, constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
    return rc_sub_slot


def __get_cc_sub_slot(sub_slots: List[SubSlotData], idx, ses: Optional[SubEpochSummary]) -> ChallengeChainSubSlot:
    sub_slot = None
    for i in reversed(range(0, idx)):
        sub_slot = sub_slots[i]
        if sub_slot.cc_slot_end_info is not None:
            break

    assert sub_slot is not None
    assert sub_slot.cc_slot_end_info is not None
    icc_vdf = sub_slot.icc_slot_end_info
    icc_vdf_hash = None
    if icc_vdf is not None:
        icc_vdf_hash = icc_vdf.get_hash()
    cc_sub_slot = ChallengeChainSubSlot(sub_slot.cc_slot_end_info, icc_vdf_hash, None if ses is None else ses.get_hash(), None if ses is None else ses.new_sub_slot_iters, None if ses is None else ses.new_difficulty)
    return cc_sub_slot


def _get_curr_diff_ssi(constants: ConsensusConstants, idx, summaries):
    curr_difficulty = constants.DIFFICULTY_STARTING
    curr_ssi = constants.SUB_SLOT_ITERS_STARTING
    for ses in reversed(summaries[0:idx]):
        if ses.new_sub_slot_iters is not None:
            curr_ssi = ses.new_sub_slot_iters
            curr_difficulty = ses.new_difficulty
            break

    return (curr_difficulty, curr_ssi)


def vars_to_bytes(constants, summaries, weight_proof):
    constants_dict = recurse_jsonify(dataclasses.asdict(constants))
    wp_recent_chain_bytes = bytes(RecentChainData(weight_proof.recent_chain_data))
    wp_segment_bytes = bytes(SubEpochSegments(weight_proof.sub_epoch_segments))
    summary_bytes = []
    for summary in summaries:
        summary_bytes.append(bytes(summary))

    return (constants_dict, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes)


def bytes_to_vars(constants_dict, summaries_bytes):
    summaries = []
    for summary in summaries_bytes:
        summaries.append(SubEpochSummary.from_bytes(summary))

    constants = dataclass_from_dict(ConsensusConstants, constants_dict)
    return (
     constants, summaries)


def _get_last_ses_hash(constants: ConsensusConstants, recent_reward_chain: List[HeaderBlock]) -> Tuple[(Optional[bytes32], uint32)]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        if block.reward_chain_block.height % constants.SUB_EPOCH_BLOCKS == 0:
            idx = len(recent_reward_chain) - 1 - idx
            while idx < len(recent_reward_chain):
                curr = recent_reward_chain[idx]
                if len(curr.finished_sub_slots) > 0:
                    for slot in curr.finished_sub_slots:
                        if slot.challenge_chain.subepoch_summary_hash is not None:
                            return (
                             slot.challenge_chain.subepoch_summary_hash,
                             curr.reward_chain_block.height)

                idx += 1

    return (
     None, uint32(0))


def _get_ses_idx(recent_reward_chain: List[HeaderBlock]) -> List[int]:
    idxs = []
    for idx, curr in enumerate(recent_reward_chain):
        if len(curr.finished_sub_slots) > 0:
            for slot in curr.finished_sub_slots:
                if slot.challenge_chain.subepoch_summary_hash is not None:
                    idxs.append(idx)

    return idxs


def get_deficit(constants, curr_deficit, prev_block, overflow, num_finished_sub_slots):
    if prev_block is None:
        if curr_deficit >= 1:
            if overflow and not curr_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                curr_deficit -= 1
            return curr_deficit
    return calculate_deficit(constants, uint32(prev_block.height + 1), prev_block, overflow, num_finished_sub_slots)


def get_sp_total_iters(constants, is_overflow, ssi, sub_slot_data):
    assert sub_slot_data.cc_ip_vdf_info is not None
    assert sub_slot_data.total_iters is not None
    assert sub_slot_data.signage_point_index is not None
    sp_iters = calculate_sp_iters(constants, ssi, sub_slot_data.signage_point_index)
    ip_iters = sub_slot_data.cc_ip_vdf_info.number_of_iterations
    sp_sub_slot_total_iters = uint128(sub_slot_data.total_iters - ip_iters)
    if is_overflow:
        sp_sub_slot_total_iters = uint128(sp_sub_slot_total_iters - ssi)
    return sp_sub_slot_total_iters + sp_iters


def blue_boxed_end_of_slot(sub_slot: EndOfSubSlotBundle):
    if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None:
            if sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity:
                return True
        else:
            return True
    return False


def validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
    tip = weight_proof.recent_chain_data[-1]
    weight_to_check = _get_weights_for_sampling(rng, tip.weight, weight_proof.recent_chain_data)
    sampled_sub_epochs = {}
    for idx in range(1, len(sub_epoch_weight_list)):
        if _sample_sub_epoch(sub_epoch_weight_list[idx - 1], sub_epoch_weight_list[idx], weight_to_check):
            sampled_sub_epochs[idx - 1] = True
            if len(sampled_sub_epochs) == WeightProofHandler.MAX_SAMPLES:
                break

    curr_sub_epoch_n = -1
    for sub_epoch_segment in weight_proof.sub_epoch_segments:
        if curr_sub_epoch_n < sub_epoch_segment.sub_epoch_n:
            if sub_epoch_segment.sub_epoch_n in sampled_sub_epochs:
                del sampled_sub_epochs[sub_epoch_segment.sub_epoch_n]
        curr_sub_epoch_n = sub_epoch_segment.sub_epoch_n

    if len(sampled_sub_epochs) > 0:
        return False
    return True


def map_segments_by_sub_epoch(sub_epoch_segments) -> Dict[(int, List[SubEpochChallengeSegment])]:
    segments = {}
    curr_sub_epoch_n = -1
    for idx, segment in enumerate(sub_epoch_segments):
        if curr_sub_epoch_n < segment.sub_epoch_n:
            curr_sub_epoch_n = segment.sub_epoch_n
            segments[curr_sub_epoch_n] = []
        else:
            segments[curr_sub_epoch_n].append(segment)

    return segments


def validate_total_iters(segment, sub_slot_data_idx, expected_sub_slot_iters, finished_sub_slots_since_prev, prev_b, prev_sub_slot_data_iters, genesis):
    sub_slot_data = segment.sub_slots[sub_slot_data_idx]
    if genesis:
        total_iters = uint128(expected_sub_slot_iters * finished_sub_slots_since_prev)
    else:
        if segment.sub_slots[sub_slot_data_idx - 1].is_end_of_slot():
            assert prev_b.total_iters
            assert prev_b.cc_ip_vdf_info
            total_iters = prev_b.total_iters
            total_iters = uint128(total_iters + prev_sub_slot_data_iters - prev_b.cc_ip_vdf_info.number_of_iterations)
            total_iters = uint128(total_iters + expected_sub_slot_iters * (finished_sub_slots_since_prev - 1))
        else:
            assert prev_b.cc_ip_vdf_info
            assert prev_b.total_iters
            total_iters = uint128(prev_b.total_iters - prev_b.cc_ip_vdf_info.number_of_iterations)
    total_iters = uint128(total_iters + sub_slot_data.cc_ip_vdf_info.number_of_iterations)
    return total_iters == sub_slot_data.total_iters