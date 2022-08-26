# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\timelord\timelord.py
import asyncio, dataclasses, io, logging, random, time, traceback
from typing import Callable, Dict, List, Optional, Tuple, Set
from chiavdf import create_discriminant
from chia.consensus.constants import ConsensusConstants
from chia.consensus.pot_iterations import calculate_sp_iters, is_overflow_block
from chia.protocols import timelord_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ChiaServer
import chia.timelord.iters_from_block as iters_from_block
from chia.timelord.timelord_state import LastState
from chia.timelord.types import Chain, IterationType, StateType
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint8, uint32, uint64, uint128
log = logging.getLogger(__name__)

class Timelord:

    def __init__(self, root_path, config: Dict, constants: ConsensusConstants):
        self.config = config
        self.root_path = root_path
        self.constants = constants
        self._shut_down = False
        self.free_clients = []
        self.potential_free_clients = []
        self.ip_whitelist = self.config['vdf_clients']['ip']
        self.server = None
        self.chain_type_to_stream = {}
        self.chain_start_time = {}
        self.unspawned_chains = [
         Chain.CHALLENGE_CHAIN,
         Chain.REWARD_CHAIN,
         Chain.INFUSED_CHALLENGE_CHAIN]
        self.allows_iters = []
        self.new_peak = None
        self.new_subslot_end = None
        self.unfinished_blocks = []
        self.signage_point_iters = []
        self.iters_to_submit = {}
        self.iters_submitted = {}
        self.iters_finished = set()
        self.iteration_to_proof_type = {}
        self.proofs_finished = []
        self.overflow_blocks = []
        self.num_resets = 0
        self.process_communication_tasks = []
        self.main_loop = None
        self.vdf_server = None
        self._shut_down = False
        self.vdf_failures = []
        self.vdf_failures_count = 0
        self.vdf_failure_time = 0
        self.total_unfinished = 0
        self.total_infused = 0
        self.state_changed_callback = None
        self.sanitizer_mode = self.config['sanitizer_mode']
        self.pending_bluebox_info = []
        self.last_active_time = time.time()

    async def _start(self):
        self.lock = asyncio.Lock()
        self.vdf_server = await asyncio.start_server(self._handle_client, self.config['vdf_server']['host'], self.config['vdf_server']['port'])
        self.last_state = LastState(self.constants)
        if not self.sanitizer_mode:
            self.main_loop = asyncio.create_task(self._manage_chains())
        else:
            self.main_loop = asyncio.create_task(self._manage_discriminant_queue_sanitizer())
        log.info('Started timelord.')

    def _close(self):
        self._shut_down = True
        for task in self.process_communication_tasks:
            task.cancel()

        if self.main_loop is not None:
            self.main_loop.cancel()

    async def _await_closed(self):
        pass

    def set_server(self, server: ChiaServer):
        self.server = server

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async with self.lock:
            client_ip = writer.get_extra_info('peername')[0]
            log.debug(f"New timelord connection from client: {client_ip}.")
            if client_ip in self.ip_whitelist:
                self.free_clients.append((client_ip, reader, writer))
                log.debug(f"Added new VDF client {client_ip}.")
                for ip, end_time in list(self.potential_free_clients):
                    if ip == client_ip:
                        self.potential_free_clients.remove((ip, end_time))
                        break

    async def _stop_chain(self, chain: Chain):
        try:
            while chain not in self.allows_iters:
                self.lock.release()
                await asyncio.sleep(0.05)
                log.error(f"Trying to stop {chain} before its initialization.")
                await self.lock.acquire()
                if chain not in self.chain_type_to_stream:
                    log.warning(f"Trying to stop a crashed chain: {chain}.")
                    return

            stop_ip, _, stop_writer = self.chain_type_to_stream[chain]
            self.potential_free_clients.append((stop_ip, time.time()))
            stop_writer.write(b'010')
            await stop_writer.drain()
            if chain in self.allows_iters:
                self.allows_iters.remove(chain)
            if chain not in self.unspawned_chains:
                self.unspawned_chains.append(chain)
            if chain in self.chain_type_to_stream:
                del self.chain_type_to_stream[chain]
        except ConnectionResetError as e:
            try:
                log.error(f"{e}")
            finally:
                e = None
                del e

    def _can_infuse_unfinished_block(self, block: timelord_protocol.NewUnfinishedBlockTimelord) -> Optional[uint64]:
        assert self.last_state is not None
        sub_slot_iters = self.last_state.get_sub_slot_iters()
        difficulty = self.last_state.get_difficulty()
        ip_iters = self.last_state.get_last_ip()
        rc_block = block.reward_chain_block
        try:
            block_sp_iters, block_ip_iters = iters_from_block(self.constants, rc_block, sub_slot_iters, difficulty)
        except Exception as e:
            try:
                log.warning(f"Received invalid unfinished block: {e}.")
                return
            finally:
                e = None
                del e

        block_sp_total_iters = self.last_state.total_iters - ip_iters + block_sp_iters
        if is_overflow_block(self.constants, block.reward_chain_block.signage_point_index):
            block_sp_total_iters -= self.last_state.get_sub_slot_iters()
        found_index = -1
        for index, (rc, total_iters) in enumerate(self.last_state.reward_challenge_cache):
            if rc == block.rc_prev:
                found_index = index
                break

        if found_index == -1:
            log.warning(f"Will not infuse {block.rc_prev} because its reward chain challenge is not in the chain")
            return
        if ip_iters > block_ip_iters:
            log.warning('Too late to infuse block')
            return
        new_block_iters = uint64(block_ip_iters - ip_iters)
        if len(self.last_state.reward_challenge_cache) > found_index + 1:
            if self.last_state.reward_challenge_cache[found_index + 1][1] < block_sp_total_iters:
                log.warning(f"Will not infuse unfinished block {block.rc_prev} sp total iters {block_sp_total_iters}, because there is another infusion before its SP")
                return
            if self.last_state.reward_challenge_cache[found_index][1] > block_sp_total_iters:
                if not is_overflow_block(self.constants, block.reward_chain_block.signage_point_index):
                    log.error(f"Will not infuse unfinished block {block.rc_prev}, sp total iters: {block_sp_total_iters}, because its iters are too low")
                return
        if new_block_iters > 0:
            return new_block_iters

    async def _reset_chains(self, first_run=False, only_eos=False):
        self.last_active_time = time.time()
        log.debug('Resetting chains')
        ip_iters = self.last_state.get_last_ip()
        sub_slot_iters = self.last_state.get_sub_slot_iters()
        if not first_run:
            for chain in list(self.chain_type_to_stream.keys()):
                await self._stop_chain(chain)

        iters_per_signage = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
        self.signage_point_iters = [(k * iters_per_signage - ip_iters, k) for k in range(1, self.constants.NUM_SPS_SUB_SLOT) if k * iters_per_signage - ip_iters > 0]
        for sp, k in self.signage_point_iters:
            assert k * iters_per_signage > 0
            if not k * iters_per_signage < sub_slot_iters:
                raise AssertionError

        new_unfinished_blocks = []
        self.iters_finished = set()
        self.proofs_finished = []
        self.num_resets += 1
        for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN, Chain.INFUSED_CHALLENGE_CHAIN]:
            self.iters_to_submit[chain] = []
            self.iters_submitted[chain] = []

        self.iteration_to_proof_type = {}
        if not only_eos:
            for block in self.unfinished_blocks + self.overflow_blocks:
                new_block_iters = self._can_infuse_unfinished_block(block)
                if new_block_iters:
                    if new_block_iters not in self.iters_to_submit[Chain.CHALLENGE_CHAIN]:
                        if block not in self.unfinished_blocks:
                            self.total_unfinished += 1
                        else:
                            new_unfinished_blocks.append(block)
                            for chain in [Chain.REWARD_CHAIN, Chain.CHALLENGE_CHAIN]:
                                self.iters_to_submit[chain].append(new_block_iters)

                            if self.last_state.get_deficit() < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                                self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(new_block_iters)
                            self.iteration_to_proof_type[new_block_iters] = IterationType.INFUSION_POINT

        self.unfinished_blocks = new_unfinished_blocks
        if not only_eos:
            if len(self.signage_point_iters) > 0:
                count_signage = 0
                for signage, k in self.signage_point_iters:
                    for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                        self.iters_to_submit[chain].append(signage)

                    self.iteration_to_proof_type[signage] = IterationType.SIGNAGE_POINT
                    count_signage += 1
                    if count_signage == 3:
                        break

        left_subslot_iters = sub_slot_iters - ip_iters
        assert left_subslot_iters > 0
        if self.last_state.get_deficit() < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
            self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.REWARD_CHAIN].append(left_subslot_iters)
        self.iteration_to_proof_type[left_subslot_iters] = IterationType.END_OF_SUBSLOT
        for chain, iters in self.iters_to_submit.items():
            for iteration in iters:
                if not iteration > 0:
                    raise AssertionError

    async def _handle_new_peak(self):
        assert self.new_peak is not None
        self.last_state.set_state(self.new_peak)
        if self.total_unfinished > 0:
            remove_unfinished = []
            for unf_block_timelord in self.unfinished_blocks + self.overflow_blocks:
                if unf_block_timelord.reward_chain_block.get_hash() == self.new_peak.reward_chain_block.get_unfinished().get_hash():
                    if unf_block_timelord not in self.unfinished_blocks:
                        self.total_unfinished += 1
                    else:
                        remove_unfinished.append(unf_block_timelord)

            if len(remove_unfinished) > 0:
                self.total_infused += 1
            for block in remove_unfinished:
                if block in self.unfinished_blocks:
                    self.unfinished_blocks.remove(block)
                if block in self.overflow_blocks:
                    self.overflow_blocks.remove(block)

            infusion_rate = round(self.total_infused / self.total_unfinished * 100.0, 2)
            log.info(f"Total unfinished blocks: {self.total_unfinished}. Total infused blocks: {self.total_infused}. Infusion rate: {infusion_rate}%.")
        self.new_peak = None
        await self._reset_chains()

    async def _handle_subslot_end(self):
        self.last_state.set_state(self.new_subslot_end)
        for block in self.unfinished_blocks:
            if self._can_infuse_unfinished_block(block) is not None:
                self.total_unfinished += 1

        self.new_subslot_end = None
        await self._reset_chains()

    async def _map_chains_with_vdf_clients(self):
        while not self._shut_down:
            picked_chain = None
            async with self.lock:
                if len(self.free_clients) == 0:
                    break
                else:
                    ip, reader, writer = self.free_clients[0]
                    for chain_type in self.unspawned_chains:
                        challenge = self.last_state.get_challenge(chain_type)
                        initial_form = self.last_state.get_initial_form(chain_type)
                        if challenge is not None:
                            if initial_form is not None:
                                picked_chain = chain_type
                                break

                if picked_chain is None:
                    break
                else:
                    picked_chain = self.unspawned_chains[0]
                    self.chain_type_to_stream[picked_chain] = (ip, reader, writer)
                    self.free_clients = self.free_clients[1:]
                    self.unspawned_chains = self.unspawned_chains[1:]
                    self.chain_start_time[picked_chain] = time.time()
            log.debug(f"Mapping free vdf_client with chain: {picked_chain}.")
            self.process_communication_tasks.append(asyncio.create_task(self._do_process_communication(picked_chain,
              challenge, initial_form, ip, reader, writer, proof_label=(self.num_resets))))

    async def _submit_iterations(self):
        for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN, Chain.INFUSED_CHALLENGE_CHAIN]:
            if chain in self.allows_iters:
                _, _, writer = self.chain_type_to_stream[chain]
                for iteration in self.iters_to_submit[chain]:
                    if iteration in self.iters_submitted[chain]:
                        continue
                    else:
                        log.debug(f"Submitting iterations to {chain}: {iteration}")
                        assert iteration > 0
                        prefix = str(len(str(iteration)))
                        if len(str(iteration)) < 10:
                            prefix = '0' + prefix
                        iter_str = prefix + str(iteration)
                        writer.write(iter_str.encode())
                        await writer.drain()
                        self.iters_submitted[chain].append(iteration)

    def _clear_proof_list(self, iters: uint64):
        return [(chain, info, proof, label) for chain, info, proof, label in self.proofs_finished if info.number_of_iterations != iters]

    async def _check_for_new_sp(self, iter_to_look_for: uint64):
        signage_iters = [iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.SIGNAGE_POINT]
        if len(signage_iters) == 0:
            return
        to_remove = []
        for potential_sp_iters, signage_point_index in self.signage_point_iters:
            if not potential_sp_iters not in signage_iters:
                if potential_sp_iters != iter_to_look_for:
                    continue
                else:
                    signage_iter = potential_sp_iters
                    proofs_with_iter = [(chain, info, proof) for chain, info, proof, label in self.proofs_finished if info.number_of_iterations == signage_iter if label == self.num_resets]
                if len(proofs_with_iter) == 2:
                    cc_info = None
                    cc_proof = None
                    rc_info = None
                    rc_proof = None
                    for chain, info, proof in proofs_with_iter:
                        if chain == Chain.CHALLENGE_CHAIN:
                            cc_info = info
                            cc_proof = proof
                        if chain == Chain.REWARD_CHAIN:
                            rc_info = info
                            rc_proof = proof

                    if cc_info is None or cc_proof is None or rc_info is None or rc_proof is None:
                        log.error(f"Insufficient signage point data {signage_iter}")
                        continue
                    else:
                        self.iters_finished.add(iter_to_look_for)
                        self.last_active_time = time.time()
                        rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
                    if rc_info.challenge != rc_challenge:
                        if not rc_challenge is not None:
                            raise AssertionError
                        else:
                            log.warning(f"SP: Do not have correct challenge {rc_challenge.hex()} has {rc_info.challenge}")
                        continue
                    else:
                        iters_from_sub_slot_start = cc_info.number_of_iterations + self.last_state.get_last_ip()
                        print('[_check_for_new_sp] signage_point_index', signage_point_index)
                        response = timelord_protocol.NewSignagePointVDF(signage_point_index, dataclasses.replace(cc_info, number_of_iterations=iters_from_sub_slot_start), cc_proof, rc_info, rc_proof)
                        if self.server is not None:
                            msg = make_msg(ProtocolMessageTypes.new_signage_point_vdf, response)
                            await self.server.send_to_all([msg], NodeType.FULL_NODE)
                        to_remove.append((signage_iter, signage_point_index))
                        self.proofs_finished = self._clear_proof_list(signage_iter)
                        next_iters_count = 0
                        for next_sp, k in self.signage_point_iters:
                            for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                                if next_sp not in self.iters_submitted[chain]:
                                    if next_sp not in self.iters_to_submit[chain]:
                                        self.iters_to_submit[chain].append(next_sp)

                            self.iteration_to_proof_type[next_sp] = IterationType.SIGNAGE_POINT
                            next_iters_count += 1
                            if next_iters_count == 3:
                                break

                    break

        for r in to_remove:
            self.signage_point_iters.remove(r)

    async def _check_for_new_ip(self, iter_to_look_for: uint64):
        if len(self.unfinished_blocks) == 0:
            return
        infusion_iters = [iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.INFUSION_POINT]
        for iteration in infusion_iters:
            if iteration != iter_to_look_for:
                continue
            else:
                proofs_with_iter = [(chain, info, proof) for chain, info, proof, label in self.proofs_finished if info.number_of_iterations == iteration if label == self.num_resets]
                if self.last_state.get_challenge(Chain.INFUSED_CHALLENGE_CHAIN) is not None:
                    chain_count = 3
                else:
                    chain_count = 2
            if len(proofs_with_iter) == chain_count:
                block = None
                ip_iters = None
                for unfinished_block in self.unfinished_blocks:
                    try:
                        _, ip_iters = iters_from_block(self.constants, unfinished_block.reward_chain_block, self.last_state.get_sub_slot_iters(), self.last_state.get_difficulty())
                    except Exception as e:
                        try:
                            log.error(f"Error {e}")
                            continue
                        finally:
                            e = None
                            del e

                    if ip_iters - self.last_state.get_last_ip() == iteration:
                        block = unfinished_block
                        break

                assert ip_iters is not None
                if block is not None:
                    print('[_check_for_new_ip] new_infusion_point_vdf beg')
                    ip_total_iters = self.last_state.get_total_iters() + iteration
                    challenge = block.reward_chain_block.get_hash()
                    icc_info = None
                    icc_proof = None
                    cc_info = None
                    cc_proof = None
                    rc_info = None
                    rc_proof = None
                    for chain, info, proof in proofs_with_iter:
                        if chain == Chain.CHALLENGE_CHAIN:
                            cc_info = info
                            cc_proof = proof
                        elif chain == Chain.REWARD_CHAIN:
                            rc_info = info
                            rc_proof = proof
                        if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                            icc_info = info
                            icc_proof = proof

            if cc_info is None or cc_proof is None or rc_info is None or rc_proof is None:
                log.error(f"Insufficient VDF proofs for infusion point ch: {challenge} iterations:{iteration}")
                return
            else:
                rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
            if rc_info.challenge != rc_challenge:
                if not rc_challenge is not None:
                    raise AssertionError
                else:
                    log.warning(f"Do not have correct challenge {rc_challenge.hex()} has {rc_info.challenge}, partial hash {block.reward_chain_block.get_hash()}")
                continue
            else:
                self.iters_finished.add(iter_to_look_for)
                self.last_active_time = time.time()
                log.debug(f"Generated infusion point for challenge: {challenge} iterations: {iteration}.")
                overflow = is_overflow_block(self.constants, block.reward_chain_block.signage_point_index)
                if not self.last_state.can_infuse_block(overflow):
                    log.warning('Too many blocks, or overflow in new epoch, cannot infuse, discarding')
                    return
                cc_info = dataclasses.replace(cc_info, number_of_iterations=ip_iters)
                response = timelord_protocol.NewInfusionPointVDF(challenge, cc_info, cc_proof, rc_info, rc_proof, icc_info, icc_proof)
                msg = make_msg(ProtocolMessageTypes.new_infusion_point_vdf, response)
                print('[_check_for_new_ip] new_infusion_point_vdf  signage_point_index:', block.reward_chain_block.signage_point_index, challenge)
                if self.server is not None:
                    await self.server.send_to_all([msg], NodeType.FULL_NODE)
                self.proofs_finished = self._clear_proof_list(iteration)
            if self.last_state.get_last_block_total_iters() is None:
                if not self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                    return
                sp_total_iters = ip_total_iters - ip_iters + calculate_sp_iters(self.constants, block.sub_slot_iters, block.reward_chain_block.signage_point_index) - (block.sub_slot_iters if overflow else 0)
                if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                    is_transaction_block = True
                    height = uint32(0)
                else:
                    last_block_ti = self.last_state.get_last_block_total_iters()
                    assert last_block_ti is not None
                    is_transaction_block = last_block_ti < sp_total_iters
                    height = uint32(self.last_state.get_height() + 1)
                if height < 5:
                    return
                else:
                    new_reward_chain_block = RewardChainBlock(uint128(self.last_state.get_weight() + block.difficulty), height, uint128(ip_total_iters), block.reward_chain_block.signage_point_index, block.reward_chain_block.pos_ss_cc_challenge_hash, block.reward_chain_block.proof_of_space, block.reward_chain_block.challenge_chain_sp_vdf, block.reward_chain_block.challenge_chain_sp_signature, cc_info, block.reward_chain_block.reward_chain_sp_vdf, block.reward_chain_block.reward_chain_sp_signature, rc_info, icc_info, is_transaction_block)
                    if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                        new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1
                    else:
                        if overflow and self.last_state.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                            if self.last_state.peak is not None:
                                assert self.last_state.subslot_end is None
                                new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                            else:
                                assert self.last_state.subslot_end is not None
                                if self.last_state.subslot_end.infused_challenge_chain is None:
                                    new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1
                                else:
                                    new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                        else:
                            new_deficit = max(self.last_state.deficit - 1, 0)
                    if new_deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                        last_csb_or_eos = ip_total_iters
                    else:
                        last_csb_or_eos = self.last_state.last_challenge_sb_or_eos_total_iters
                    if self.last_state.just_infused_sub_epoch_summary():
                        new_sub_epoch_summary = None
                        passed_ses_height_but_not_yet_included = False
                    else:
                        new_sub_epoch_summary = block.sub_epoch_summary
                        if new_reward_chain_block.height % self.constants.SUB_EPOCH_BLOCKS == 0:
                            passed_ses_height_but_not_yet_included = True
                        else:
                            passed_ses_height_but_not_yet_included = self.last_state.get_passed_ses_height_but_not_yet_included()
                    self.new_peak = timelord_protocol.NewPeakTimelord(new_reward_chain_block, block.difficulty, uint8(new_deficit), block.sub_slot_iters, new_sub_epoch_summary, self.last_state.reward_challenge_cache, uint128(last_csb_or_eos), passed_ses_height_but_not_yet_included)
                    await self._handle_new_peak()
                break

    async def _check_for_end_of_subslot(self, iter_to_look_for: uint64):
        left_subslot_iters = [iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.END_OF_SUBSLOT]
        if len(left_subslot_iters) == 0:
            return
        if left_subslot_iters[0] != iter_to_look_for:
            return
        chains_finished = [(chain, info, proof) for chain, info, proof, label in self.proofs_finished if info.number_of_iterations == left_subslot_iters[0] if label == self.num_resets]
        if self.last_state.get_challenge(Chain.INFUSED_CHALLENGE_CHAIN) is not None:
            chain_count = 3
        else:
            chain_count = 2
        if len(chains_finished) == chain_count:
            icc_ip_vdf = None
            icc_ip_proof = None
            cc_vdf = None
            cc_proof = None
            rc_vdf = None
            rc_proof = None
            for chain, info, proof in chains_finished:
                if chain == Chain.CHALLENGE_CHAIN:
                    cc_vdf = info
                    cc_proof = proof
                elif chain == Chain.REWARD_CHAIN:
                    rc_vdf = info
                    rc_proof = proof
                if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                    icc_ip_vdf = info
                    icc_ip_proof = proof

            if cc_proof is not None:
                if rc_proof is not None:
                    if not (cc_vdf is not None and rc_vdf is not None):
                        raise AssertionError
                    rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
                    if rc_vdf.challenge != rc_challenge:
                        assert rc_challenge is not None
                        log.warning(f"Do not have correct challenge {rc_challenge.hex()} has {rc_vdf.challenge}")
                        return
                    log.debug('Collected end of subslot vdfs.')
                    self.iters_finished.add(iter_to_look_for)
                    self.last_active_time = time.time()
                    iters_from_sub_slot_start = cc_vdf.number_of_iterations + self.last_state.get_last_ip()
                    cc_vdf = dataclasses.replace(cc_vdf, number_of_iterations=iters_from_sub_slot_start)
                    if icc_ip_vdf is not None:
                        if self.last_state.peak is not None:
                            total_iters = self.last_state.get_total_iters() - self.last_state.get_last_ip() + self.last_state.get_sub_slot_iters()
                        else:
                            total_iters = self.last_state.get_total_iters() + self.last_state.get_sub_slot_iters()
                        iters_from_cb = uint64(total_iters - self.last_state.last_challenge_sb_or_eos_total_iters)
                        if iters_from_cb > self.last_state.sub_slot_iters:
                            log.error(f"{self.last_state.peak}")
                            log.error(f"{self.last_state.subslot_end}")
                            assert False
                            if not iters_from_cb <= self.last_state.sub_slot_iters:
                                raise AssertionError
                        icc_ip_vdf = dataclasses.replace(icc_ip_vdf, number_of_iterations=iters_from_cb)
                    icc_sub_slot = None if icc_ip_vdf is None else InfusedChallengeChainSubSlot(icc_ip_vdf)
                    if self.last_state.get_deficit() == 0:
                        assert icc_sub_slot is not None
                        icc_sub_slot_hash = icc_sub_slot.get_hash()
                    else:
                        icc_sub_slot_hash = None
                    next_ses = self.last_state.get_next_sub_epoch_summary()
                    if next_ses is not None:
                        log.info(f"Including sub epoch summary{next_ses}")
                        ses_hash = next_ses.get_hash()
                        new_sub_slot_iters = next_ses.new_sub_slot_iters
                        new_difficulty = next_ses.new_difficulty
                    else:
                        ses_hash = None
                        new_sub_slot_iters = None
                        new_difficulty = None
                    cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot_hash, ses_hash, new_sub_slot_iters, new_difficulty)
                    eos_deficit = self.last_state.get_deficit() if (self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK> self.last_state.get_deficit() > 0) else (self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK)
                    rc_sub_slot = RewardChainSubSlot(rc_vdf, cc_sub_slot.get_hash(), icc_sub_slot.get_hash() if icc_sub_slot is not None else None, eos_deficit)
                    eos_bundle = EndOfSubSlotBundle(cc_sub_slot, icc_sub_slot, rc_sub_slot, SubSlotProofs(cc_proof, icc_ip_proof, rc_proof))
                    if self.server is not None:
                        msg = make_msg(ProtocolMessageTypes.new_end_of_sub_slot_vdf, timelord_protocol.NewEndOfSubSlotVDF(eos_bundle))
                        await self.server.send_to_all([msg], NodeType.FULL_NODE)
                log.info(f"Built end of subslot bundle. cc hash: {eos_bundle.challenge_chain.get_hash()}. New_difficulty: {eos_bundle.challenge_chain.new_difficulty} New ssi: {eos_bundle.challenge_chain.new_sub_slot_iters}")
                if next_ses is None or next_ses.new_difficulty is None:
                    self.unfinished_blocks = self.overflow_blocks.copy()
                else:
                    self.unfinished_blocks = []
                self.overflow_blocks = []
                self.new_subslot_end = eos_bundle
                await self._handle_subslot_end()

    async def _handle_failures(self):
        if len(self.vdf_failures) > 0:
            failed_chain, proof_label = self.vdf_failures[0]
            log.error(f"Vdf clients failed {self.vdf_failures_count} times. Last failure: {failed_chain}, label {proof_label}, current: {self.num_resets}")
            if proof_label == self.num_resets:
                await self._reset_chains(only_eos=True)
            self.vdf_failure_time = time.time()
            self.vdf_failures = []
        if time.time() - self.vdf_failure_time < self.constants.SUB_SLOT_TIME_TARGET * 3:
            active_time_threshold = self.constants.SUB_SLOT_TIME_TARGET * 3
        else:
            active_time_threshold = 60
        if time.time() - self.last_active_time > active_time_threshold:
            log.error(f"Not active for {active_time_threshold} seconds, restarting all chains")
            await self._reset_chains()

    async def _manage_chains(self):
        async with self.lock:
            await asyncio.sleep(5)
            await self._reset_chains(True)
        countx = 1
        while not self._shut_down:
            try:
                countx += 1
                await asyncio.sleep(0.1)
                async with self.lock:
                    await self._handle_failures()
                    if self.new_peak is not None:
                        await self._handle_new_peak()
                await self._map_chains_with_vdf_clients()
                async with self.lock:
                    await self._submit_iterations()
                    not_finished_iters = [it for it in self.iters_submitted[Chain.REWARD_CHAIN] if it not in self.iters_finished]
                    if countx % 100 == 0:
                        print('still here....')
                    if len(not_finished_iters) == 0:
                        await asyncio.sleep(0.1)
                        continue
                    else:
                        selected_iter = min(not_finished_iters)
                        await self._check_for_new_ip(selected_iter)
                        await self._check_for_new_sp(selected_iter)
                        await self._check_for_end_of_subslot(selected_iter)
            except Exception:
                tb = traceback.format_exc()
                log.error(f"Error while handling message: {tb}")

    async def _do_process_communication(self, chain: Chain, challenge: bytes32, initial_form: ClassgroupElement, ip: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bluebox_iteration: Optional[uint64]=None, header_hash: Optional[bytes32]=None, height: Optional[uint32]=None, field_vdf: Optional[uint8]=None, proof_label: Optional[int]=None):
        disc = create_discriminant(challenge, self.constants.DISCRIMINANT_SIZE_BITS)
        try:
            async with self.lock:
                if self.sanitizer_mode:
                    writer.write(b'S')
                else:
                    if self.config['fast_algorithm']:
                        writer.write(b'N')
                    else:
                        writer.write(b'T')
                await writer.drain()
            prefix = str(len(str(disc)))
            if len(prefix) == 1:
                prefix = '00' + prefix
            if len(prefix) == 2:
                prefix = '0' + prefix
            async with self.lock:
                writer.write((prefix + str(disc)).encode())
                await writer.drain()
            async with self.lock:
                writer.write(bytes([len(initial_form.data)]) + initial_form.data)
                await writer.drain()
            try:
                ok = await reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionResetError, Exception) as e:
                try:
                    log.warning(f"{type(e)} {e}")
                    async with self.lock:
                        self.vdf_failures.append((chain, proof_label))
                        self.vdf_failures_count += 1
                    return
                finally:
                    e = None
                    del e

            if ok.decode() != 'OK':
                return
            log.debug('Got handshake with VDF client.')
            if not self.sanitizer_mode:
                async with self.lock:
                    self.allows_iters.append(chain)
            else:
                async with self.lock:
                    assert chain is Chain.BLUEBOX
                    assert bluebox_iteration is not None
                    prefix = str(len(str(bluebox_iteration)))
                    if len(str(bluebox_iteration)) < 10:
                        prefix = '0' + prefix
                    iter_str = prefix + str(bluebox_iteration)
                    writer.write(iter_str.encode())
                    await writer.drain()
            while 1:
                try:
                    data = await reader.readexactly(4)
                except (asyncio.IncompleteReadError,
                 ConnectionResetError,
                 Exception) as e:
                    try:
                        log.warning(f"{type(e)} {e}")
                        async with self.lock:
                            self.vdf_failures.append((chain, proof_label))
                            self.vdf_failures_count += 1
                        break
                    finally:
                        e = None
                        del e

                msg = ''
                try:
                    msg = data.decode()
                except Exception:
                    pass

                if msg == 'STOP':
                    log.debug(f"Stopped client running on ip {ip}.")
                    async with self.lock:
                        writer.write(b'ACK')
                        await writer.drain()
                    break
                else:
                    try:
                        length = int.from_bytes(data, 'big')
                        proof = await reader.readexactly(length)
                        stdout_bytes_io = io.BytesIO(bytes.fromhex(proof.decode()))
                    except (asyncio.IncompleteReadError,
                     ConnectionResetError,
                     Exception) as e:
                        try:
                            log.warning(f"{type(e)} {e}")
                            async with self.lock:
                                self.vdf_failures.append((chain, proof_label))
                                self.vdf_failures_count += 1
                            break
                        finally:
                            e = None
                            del e

                    iterations_needed = uint64(int.from_bytes((stdout_bytes_io.read(8)), 'big', signed=True))
                    y_size_bytes = stdout_bytes_io.read(8)
                    y_size = uint64(int.from_bytes(y_size_bytes, 'big', signed=True))
                    y_bytes = stdout_bytes_io.read(y_size)
                    witness_type = uint8(int.from_bytes((stdout_bytes_io.read(1)), 'big', signed=True))
                    proof_bytes = stdout_bytes_io.read()
                    form_size = ClassgroupElement.get_size(self.constants)
                    output = ClassgroupElement.from_bytes(y_bytes[:form_size])
                    if not self.sanitizer_mode:
                        time_taken = time.time() - self.chain_start_time[chain]
                        ips = int(iterations_needed / time_taken * 10) / 10
                        log.info(f"Finished PoT chall:{challenge[:10].hex()}.. {iterations_needed} iters, Estimated IPS: {ips}, Chain: {chain}")
                    vdf_info = VDFInfo(challenge, iterations_needed, output)
                    vdf_proof = VDFProof(witness_type, proof_bytes, self.sanitizer_mode)
                    if not vdf_proof.is_valid(self.constants, initial_form, vdf_info):
                        log.error('Invalid proof of time!')
                    if not self.sanitizer_mode:
                        async with self.lock:
                            assert proof_label is not None
                            self.proofs_finished.append((chain, vdf_info, vdf_proof, proof_label))
                async with self.lock:
                    writer.write(b'010')
                    await writer.drain()
                if not header_hash is not None:
                    raise AssertionError
                else:
                    assert field_vdf is not None
                    assert height is not None
                    response = timelord_protocol.RespondCompactProofOfTime(vdf_info, vdf_proof, header_hash, height, field_vdf)
                if self.server is not None:
                    message = make_msg(ProtocolMessageTypes.respond_compact_proof_of_time, response)
                    await self.server.send_to_all([message], NodeType.FULL_NODE)

        except ConnectionResetError as e:
            try:
                log.debug(f"Connection reset with VDF client {e}")
            finally:
                e = None
                del e

    async def _manage_discriminant_queue_sanitizer(self):
        while not self._shut_down:
            async with self.lock:
                try:
                    while len(self.pending_bluebox_info) > 0:
                        if len(self.free_clients) > 0:
                            target_field_vdf = random.randint(1, 4)
                            info = next((info for info in self.pending_bluebox_info if info[1].field_vdf == target_field_vdf), None)
                            if info is None:
                                info = self.pending_bluebox_info[0]
                            else:
                                ip, reader, writer = self.free_clients[0]
                                self.process_communication_tasks.append(asyncio.create_task(self._do_process_communication(Chain.BLUEBOX, info[1].new_proof_of_time.challenge, ClassgroupElement.get_default_element(), ip, reader, writer, info[1].new_proof_of_time.number_of_iterations, info[1].header_hash, info[1].height, info[1].field_vdf)))
                                self.pending_bluebox_info.remove(info)
                                self.free_clients = self.free_clients[1:]

                except Exception as e:
                    try:
                        log.error(f"Exception manage discriminant queue: {e}")
                    finally:
                        e = None
                        del e

            await asyncio.sleep(0.1)