# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\keychain.py
import unicodedata
from hashlib import pbkdf2_hmac
from secrets import token_bytes
from sys import platform
from typing import List, Optional, Tuple
import keyring as keyring_main, pkg_resources
from bitstring import BitArray
from blspy import AugSchemeMPL, G1Element, PrivateKey
from keyrings.cryptfile.cryptfile import CryptFileKeyring
from chia.util.hash import std_hash
MAX_KEYS = 100
if platform == 'win32' or platform == 'cygwin':
    import keyring.backends.Windows
    keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
else:
    if platform == 'darwin':
        import keyring.backends.macOS
        keyring.set_keyring(keyring.backends.macOS.Keyring())
    else:
        if platform == 'linux':
            keyring = CryptFileKeyring()
            keyring.keyring_key = 'your keyring password'
        else:
            keyring = keyring_main

def bip39_word_list() -> str:
    return pkg_resources.resource_string(__name__, 'english.txt').decode()


def generate_mnemonic() -> str:
    mnemonic_bytes = token_bytes(32)
    mnemonic = bytes_to_mnemonic(mnemonic_bytes)
    return mnemonic


def bytes_to_mnemonic(mnemonic_bytes: bytes) -> str:
    if len(mnemonic_bytes) not in (16, 20, 24, 28, 32):
        raise ValueError(f"Data length should be one of the following: [16, 20, 24, 28, 32], but it is {len(mnemonic_bytes)}.")
    word_list = bip39_word_list().splitlines()
    CS = len(mnemonic_bytes) // 4
    checksum = BitArray(bytes(std_hash(mnemonic_bytes)))[:CS]
    bitarray = BitArray(mnemonic_bytes) + checksum
    mnemonics = []
    assert len(bitarray) % 11 == 0
    for i in range(0, len(bitarray) // 11):
        start = i * 11
        end = start + 11
        bits = bitarray[start:end]
        m_word_position = bits.uint
        m_word = word_list[m_word_position]
        mnemonics.append(m_word)

    return ' '.join(mnemonics)


def bytes_from_mnemonic(mnemonic_str: str) -> bytes:
    mnemonic = mnemonic_str.split(' ')
    if len(mnemonic) not in (12, 15, 18, 21, 24):
        raise ValueError('Invalid mnemonic length')
    word_list = {word: i for i, word in enumerate(bip39_word_list().splitlines())}
    bit_array = BitArray()
    for i in range(0, len(mnemonic)):
        word = mnemonic[i]
        if word not in word_list:
            raise ValueError(f"'{word}' is not in the mnemonic dictionary; may be misspelled")
        else:
            value = word_list[word]
            bit_array.append(BitArray(uint=value, length=11))

    CS = len(mnemonic) // 3
    ENT = len(mnemonic) * 11 - CS
    assert len(bit_array) == len(mnemonic) * 11
    assert ENT % 32 == 0
    entropy_bytes = bit_array[:ENT].bytes
    checksum_bytes = bit_array[ENT:]
    checksum = BitArray(std_hash(entropy_bytes))[:CS]
    assert len(checksum_bytes) == CS
    if checksum != checksum_bytes:
        raise ValueError('Invalid order of mnemonic words')
    return entropy_bytes


def mnemonic_to_seed(mnemonic: str, passphrase: str) -> bytes:
    """
    Uses BIP39 standard to derive a seed from entropy bytes.
    """
    salt_str = 'mnemonic' + passphrase
    salt = unicodedata.normalize('NFKD', salt_str).encode('utf-8')
    mnemonic_normalized = unicodedata.normalize('NFKD', mnemonic).encode('utf-8')
    seed = pbkdf2_hmac('sha512', mnemonic_normalized, salt, 2048)
    assert len(seed) == 64
    return seed


class Keychain:
    __doc__ = '\n    The keychain stores two types of keys: private keys, which are PrivateKeys from blspy,\n    and private key seeds, which are bytes objects that are used as a seed to construct\n    PrivateKeys. Private key seeds are converted to mnemonics when shown to users.\n\n    Both types of keys are stored as hex strings in the python keyring, and the implementation of\n    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a\n    list of all keys.\n    '
    testing: bool
    user: str

    def __init__(self, user: str='user-chia-1.8', testing: bool=False):
        self.testing = testing
        self.user = user

    def _get_service(self) -> str:
        """
        The keychain stores keys under a different name for tests.
        """
        if self.testing:
            return f"chia-{self.user}-test"
        return f"chia-{self.user}"

    def _get_pk_and_entropy(self, user: str) -> Optional[Tuple[(G1Element, bytes)]]:
        """
        Returns the keychain contents for a specific 'user' (key index). The contents
        include an G1Element and the entropy required to generate the private key.
        Note that generating the actual private key also requires the passphrase.
        """
        read_str = keyring.get_password(self._get_service(), user)
        if read_str is None or len(read_str) == 0:
            return
        str_bytes = bytes.fromhex(read_str)
        return (
         G1Element.from_bytes(str_bytes[:G1Element.SIZE]),
         str_bytes[G1Element.SIZE:])

    def _get_private_key_user(self, index: int) -> str:
        """
        Returns the keychain user string for a key index.
        """
        if self.testing:
            return f"wallet-{self.user}-test-{index}"
        return f"wallet-{self.user}-{index}"

    def _get_free_private_key_index(self) -> int:
        """
        Get the index of the first free spot in the keychain.
        """
        index = 0
        while True:
            pk = self._get_private_key_user(index)
            pkent = self._get_pk_and_entropy(pk)
            if pkent is None:
                return index
            else:
                index += 1

    def add_private_key(self, mnemonic: str, passphrase: str) -> PrivateKey:
        """
        Adds a private key to the keychain, with the given entropy and passphrase. The
        keychain itself will store the public key, and the entropy bytes,
        but not the passphrase.
        """
        seed = mnemonic_to_seed(mnemonic, passphrase)
        entropy = bytes_from_mnemonic(mnemonic)
        index = self._get_free_private_key_index()
        key = AugSchemeMPL.key_gen(seed)
        fingerprint = key.get_g1().get_fingerprint()
        if fingerprint in [pk.get_fingerprint() for pk in self.get_all_public_keys()]:
            return key
        keyring.set_password(self._get_service(), self._get_private_key_user(index), bytes(key.get_g1()).hex() + entropy.hex())
        return key

    def get_first_private_key(self, passphrases: List[str]=[
 '']) -> Optional[Tuple[(PrivateKey, bytes)]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if key.get_g1() == pk:
                        return (key, ent)

            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    def get_private_key_by_fingerprint(self, fingerprint: int, passphrases: List[str]=[
 '']) -> Optional[Tuple[(PrivateKey, bytes)]]:
        """
        Return first private key which have the given public key fingerprint.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if pk.get_fingerprint() == fingerprint:
                        return (key, ent)

            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    def get_all_private_keys(self, passphrases: List[str]=[
 '']) -> List[Tuple[(PrivateKey, bytes)]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys = []
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if key.get_g1() == pk:
                        all_keys.append((key, ent))

            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

        return all_keys

    def get_all_public_keys(self) -> List[G1Element]:
        """
        Returns all public keys.
        """
        all_keys = []
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                all_keys.append(pk)
            else:
                index += 1
                pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

        return all_keys

    def get_first_public_key(self) -> Optional[G1Element]:
        """
        Returns the first public key.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                return pk
            else:
                index += 1
                pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    def delete_key_by_fingerprint(self, fingerprint: int):
        """
        Deletes all keys which have the given public key fingerprint.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                if pk.get_fingerprint() == fingerprint:
                    keyring.delete_password(self._get_service(), self._get_private_key_user(index))
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    def delete_all_keys(self):
        """
        Deletes all keys from the keychain.
        """
        index = 0
        delete_exception = False
        pkent = None
        while True:
            try:
                pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
                keyring.delete_password(self._get_service(), self._get_private_key_user(index))
            except Exception:
                delete_exception = True

            if pkent is None or delete_exception:
                if index > MAX_KEYS:
                    break
            index += 1

        index = 0
        delete_exception = True
        pkent = None
        while True:
            try:
                pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
                keyring.delete_password(self._get_service(), self._get_private_key_user(index))
            except Exception:
                delete_exception = True

            if pkent is None or delete_exception:
                if index > MAX_KEYS:
                    break
            index += 1