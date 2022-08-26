# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\plotting\check_plots.py
import logging
from collections import Counter
from pathlib import Path
from time import time
from typing import Dict, List
from blspy import G1Element
from chiapos import Verifier
from chia.plotting.plot_tools import find_duplicate_plot_IDs, get_plot_filenames, load_plots, parse_plot_info
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk
log = logging.getLogger(__name__)

def check_plots(root_path, num, challenge_start, grep_string, list_duplicates, debug_show_memo):
    config = load_config(root_path, 'config.yaml')
    if num is not None:
        if num == 0:
            log.warning('Not opening plot files')
        else:
            if num < 5:
                log.warning(f"{num} challenges is too low, setting it to the minimum of 5")
                num = 5
            if num < 30:
                log.warning('Use 30 challenges (our default) for balance of speed and accurate results')
    else:
        num = 30
    if challenge_start is not None:
        num_start = challenge_start
        num_end = num_start + num
    else:
        num_start = 0
        num_end = num
    challenges = num_end - num_start
    if list_duplicates:
        log.warning('Checking for duplicate Plot IDs')
        log.info('Plot filenames expected to end with -[64 char plot ID].plot')
    show_memo = debug_show_memo
    if list_duplicates:
        plot_filenames = get_plot_filenames(config['harvester'])
        all_filenames = []
        for paths in plot_filenames.values():
            all_filenames += paths

        find_duplicate_plot_IDs(all_filenames)
    if num == 0:
        return
    parallel_read = config['harvester'].get('parallel_read', True)
    v = Verifier()
    log.info(f"Loading plots in config.yaml using plot_tools loading code (parallel read: {parallel_read})\n")
    kc = Keychain()
    pks = [master_sk_to_farmer_sk(sk).get_g1() for sk, _ in kc.get_all_private_keys()]
    pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in config['farmer']['pool_public_keys']]
    _, provers, failed_to_open_filenames, no_key_filenames = load_plots({}, {}, pks,
      pool_public_keys,
      grep_string,
      show_memo,
      root_path,
      open_no_key_filenames=True)
    if len(provers) > 0:
        log.info('')
        log.info('')
        log.info(f"Starting to test each plot with {num} challenges each\n")
    total_good_plots = Counter()
    total_bad_plots = 0
    total_size = 0
    bad_plots_list = []
    for plot_path, plot_info in provers.items():
        pr = plot_info.prover
        log.info(f"Testing plot {plot_path} k={pr.get_size()}")
        log.info(f"\tPool public key: {plot_info.pool_public_key}")
        pool_public_key_or_puzzle_hash, farmer_public_key, local_master_sk = parse_plot_info(pr.get_memo())
        local_sk = master_sk_to_local_sk(local_master_sk)
        log.info(f"\tFarmer public key: {farmer_public_key}")
        log.info(f"\tLocal sk: {local_sk}")
        total_proofs = 0
        caught_exception = False
        for i in range(num_start, num_end):
            challenge = std_hash(i.to_bytes(32, 'big'))
            try:
                quality_start_time = int(round(time() * 1000))
                for index, quality_str in enumerate(pr.get_qualities_for_challenge(challenge)):
                    quality_spent_time = int(round(time() * 1000)) - quality_start_time
                    if quality_spent_time > 5000:
                        log.warning(f"\tLooking up qualities took: {quality_spent_time} ms. This should be below 5 seconds to minimize risk of losing rewards.")
                    else:
                        log.info(f"\tLooking up qualities took: {quality_spent_time} ms.")
                    try:
                        proof_start_time = int(round(time() * 1000))
                        proof = pr.get_full_proof(challenge, index, parallel_read)
                        proof_spent_time = int(round(time() * 1000)) - proof_start_time
                        if proof_spent_time > 15000:
                            log.warning(f"\tFinding proof took: {proof_spent_time} ms. This should be below 15 seconds to minimize risk of losing rewards.")
                        else:
                            log.info(f"\tFinding proof took: {proof_spent_time} ms")
                        total_proofs += 1
                        ver_quality_str = v.validate_proof(pr.get_id(), pr.get_size(), challenge, proof)
                        assert quality_str == ver_quality_str
                    except AssertionError as e:
                        try:
                            log.error(f"{type(e)}: {e} error in proving/verifying for plot {plot_path}")
                            caught_exception = True
                        finally:
                            e = None
                            del e

                    quality_start_time = int(round(time() * 1000))

            except KeyboardInterrupt:
                log.warning('Interrupted, closing')
                return
            except SystemExit:
                log.warning('System is shutting down.')
                return
            except Exception as e:
                try:
                    log.error(f"{type(e)}: {e} error in getting challenge qualities for plot {plot_path}")
                    caught_exception = True
                finally:
                    e = None
                    del e

            if caught_exception is True:
                break

        if total_proofs > 0 and caught_exception is False:
            log.info(f"\tProofs {total_proofs} / {challenges}, {round(total_proofs / float(challenges), 4)}")
            total_good_plots[pr.get_size()] += 1
            total_size += plot_path.stat().st_size
        else:
            total_bad_plots += 1
            log.error(f"\tProofs {total_proofs} / {challenges}, {round(total_proofs / float(challenges), 4)}")
            bad_plots_list.append(plot_path)

    log.info('')
    log.info('')
    log.info('Summary')
    total_plots = sum(list(total_good_plots.values()))
    log.info(f"Found {total_plots} valid plots, total size {total_size / 1099511627776:.5f} TiB")
    for k, count in sorted(dict(total_good_plots).items()):
        log.info(f"{count} plots of size {k}")

    grand_total_bad = total_bad_plots + len(failed_to_open_filenames)
    if grand_total_bad > 0:
        log.warning(f"{grand_total_bad} invalid plots found:")
        for bad_plot_path in bad_plots_list:
            log.warning(f"{bad_plot_path}")

    if len(no_key_filenames) > 0:
        log.warning(f"There are {len(no_key_filenames)} plots with a farmer or pool public key that is not on this machine. The farmer private key must be in the keychain in order to farm them, use 'chia keys' to transfer keys. The pool public keys must be in the config.yaml")