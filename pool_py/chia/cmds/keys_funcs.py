# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\cmds\keys_funcs.py
from typing import List
from blspy import AugSchemeMPL, G1Element, G2Element
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32
from chia.util.keychain import Keychain, bytes_to_mnemonic, generate_mnemonic
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk
keychain: Keychain = Keychain()

def generate_and_print():
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """
    mnemonic = generate_mnemonic()
    print('Generating private key. Mnemonic (24 secret words):')
    print(mnemonic)
    print('Note that this key has not been added to the keychain. Run chia keys add')
    return mnemonic


def generate_and_add():
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """
    mnemonic = generate_mnemonic()
    print('Generating private key')
    add_private_key_seed(mnemonic)


def query_and_add_private_key_seed():
    mnemonic = input('Enter the mnemonic you want to use: ')
    add_private_key_seed(mnemonic)


def add_private_key_seed(mnemonic: str):
    """
    Add a private key seed to the keyring, with the given mnemonic.
    """
    try:
        passphrase = ''
        sk = keychain.add_private_key(mnemonic, passphrase)
        fingerprint = sk.get_g1().get_fingerprint()
        print(f"Added private key with public key fingerprint {fingerprint}")
    except ValueError as e:
        try:
            print(e)
            return
        finally:
            e = None
            del e


def show_all_keys(show_mnemonic: bool):
    """
    Prints all keys and mnemonics (if available).
    """
    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, 'config.yaml')
    private_keys = keychain.get_all_private_keys()
    selected = config['selected_network']
    prefix = config['network_overrides']['config'][selected]['address_prefix']
    if len(private_keys) == 0:
        print('There are no saved private keys')
        return
    msg = 'Showing all public keys derived from your private keys:'
    if show_mnemonic:
        msg = 'Showing all public and private keys'
    print(msg)
    for sk, seed in private_keys:
        print('')
        print('Fingerprint:', sk.get_g1().get_fingerprint())
        print('Master public key (m):', sk.get_g1())
        print('Farmer public key (m/12381/8444/0/0):', master_sk_to_farmer_sk(sk).get_g1())
        print('Pool public key (m/12381/8444/1/0):', master_sk_to_pool_sk(sk).get_g1())
        print('First wallet address:', encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1()), prefix))
        assert seed is not None
        if show_mnemonic:
            print('Master private key (m):', bytes(sk).hex())
            print('First wallet secret key (m/12381/8444/2/0):', master_sk_to_wallet_sk(sk, uint32(0)))
            mnemonic = bytes_to_mnemonic(seed)
            print('  Mnemonic seed (24 secret words):')
            print(mnemonic)


def delete(fingerprint: int):
    """
    Delete a key by its public key fingerprint (which is an integer).
    """
    print(f"Deleting private_key with fingerprint {fingerprint}")
    keychain.delete_key_by_fingerprint(fingerprint)


def sign(message: str, fingerprint: int, hd_path: str):
    k = Keychain()
    private_keys = k.get_all_private_keys()
    path = [uint32(int(i)) for i in hd_path.split('/') if i != 'm']
    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            for c in path:
                sk = AugSchemeMPL.derive_child_sk(sk, c)

            print('Public key:', sk.get_g1())
            print('Signature:', AugSchemeMPL.sign(sk, bytes(message, 'utf-8')))
            return

    print(f"Fingerprint {fingerprint} not found in keychain")


def verify(message: str, public_key: str, signature: str):
    messageBytes = bytes(message, 'utf-8')
    public_key = G1Element.from_bytes(bytes.fromhex(public_key))
    signature = G2Element.from_bytes(bytes.fromhex(signature))
    print(AugSchemeMPL.verify(public_key, messageBytes, signature))