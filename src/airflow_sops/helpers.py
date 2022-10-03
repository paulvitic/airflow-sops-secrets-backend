import subprocess
import hashlib
import sys
import re

from os import environ
from typing import MutableMapping, MutableSequence
from ruamel.yaml.scalarstring import PreservedScalarString
from datetime import datetime, timedelta
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, modes, algorithms
from base64 import b64decode
from airflow.exceptions import AirflowException

SOPS_INPUT_VERSION = '1.18'

SOPS_UNENCRYPTED_SUFFIX = '_unencrypted'


def _get_key_from_pgp(tree):
    """Retrieve the key from the PGP tree leave."""
    try:
        pgp_tree = tree['sops']['pgp']
    except KeyError:
        return None
    i = -1
    for entry in pgp_tree:
        if not entry:
            continue
        i += 1
        try:
            enc = entry['enc']
        except KeyError:
            continue
        try:
            # check if the user has specified a custom GPG program.
            _set_gpg_exec()

            p = subprocess.Popen([GPG_EXEC, '--use-agent', '-d'],
                                 stdout=subprocess.PIPE,
                                 stdin=subprocess.PIPE)
            key = p.communicate(input=enc.encode('utf-8'))[0]
        except Exception as e:
            print("INFO: PGP decryption failed in entry %s with error: %s" %
                  (i, e), file=sys.stderr)
            continue
        if len(key) == 32:
            return key
    return None


def _check_rotation_needed(tree):
    """ Browse the master keys and check their creation date to
        display a warning if older than 6 months (it's time to rotate).
    """
    show_rotation_warning = False
    six_months_ago = datetime.utcnow() - timedelta(days=183)
    if 'kms' in tree['sops']:
        for entry in tree['sops']['kms']:
            if not entry:
                continue
            # check if creation date is older than 6 months
            if 'created_at' in entry:
                d = datetime.strptime(entry['created_at'],
                                      '%Y-%m-%dT%H:%M:%SZ')
                if d < six_months_ago:
                    show_rotation_warning = True

    if 'pgp' in tree['sops']:
        for entry in tree['sops']['pgp']:
            if not entry:
                continue
            # check if creation date is older than 6 months
            if 'created_at' in entry:
                d = datetime.strptime(entry['created_at'],
                                      '%Y-%m-%dT%H:%M:%SZ')
                if d < six_months_ago:
                    show_rotation_warning = True
    if show_rotation_warning:
        print("INFO: the data key on this document is over 6 months old. "
              "Considering rotating it with $ sops -r <file> ",
              file=sys.stderr)


def _walk_list_and_decrypt(branch, key, aad=b'', stash=None, digest=None,
                           unencrypted=False):
    """Walk a list contained in a branch and decrypts its values."""
    nstash = dict()
    kl = []
    for i, v in enumerate(list(branch)):
        if stash:
            stash[i] = {'has_stash': True}
            nstash = stash[i]
        if isinstance(v, MutableMapping):
            kl.append(_walk_and_decrypt(v, key, aad=aad, stash=nstash,
                                        digest=digest, isRoot=False,
                                        unencrypted=unencrypted))
        elif isinstance(v, MutableSequence):
            kl.append(_walk_list_and_decrypt(v, key, aad=aad, stash=nstash,
                                             digest=digest,
                                             unencrypted=unencrypted))
        else:
            kl.append(_decrypt(v, key, aad=aad, stash=nstash, digest=digest,
                               unencrypted=unencrypted))
    return kl


def _walk_and_decrypt(branch, key, aad=b'', stash=None, digest=None,
                      isRoot=True, ignoreMac=False, unencrypted=False):
    """Walk the branch recursively and decrypt leaves."""
    if isRoot and not ignoreMac:
        digest = hashlib.sha512()
    carryaad = aad
    for k, v in branch.items():
        if k == 'sops' and isRoot:
            continue  # everything under the `sops` key stays in clear
        unencrypted_branch = unencrypted or k.endswith(SOPS_UNENCRYPTED_SUFFIX)
        nstash = dict()
        caad = aad
        if _a_is_newer_than_b(SOPS_INPUT_VERSION, '0.9'):
            caad = aad + k.encode('utf-8') + b':'
        else:
            caad = carryaad
            caad += k.encode('utf-8')
            carryaad = caad
        if stash:
            stash[k] = {'has_stash': True}
            nstash = stash[k]
        if isinstance(v, MutableMapping):
            branch[k] = _walk_and_decrypt(v, key, aad=caad, stash=nstash,
                                          digest=digest, isRoot=False,
                                          unencrypted=unencrypted_branch)
        elif isinstance(v, MutableSequence):
            branch[k] = _walk_list_and_decrypt(v, key, aad=caad, stash=nstash,
                                               digest=digest,
                                               unencrypted=unencrypted_branch)
        elif isinstance(v, PreservedScalarString):
            ev = _decrypt(v, key, aad=caad, stash=nstash, digest=digest,
                          unencrypted=unencrypted_branch)
            branch[k] = PreservedScalarString(ev)
        else:
            branch[k] = _decrypt(v, key, aad=caad, stash=nstash, digest=digest,
                                 unencrypted=unencrypted_branch)

    if isRoot and not ignoreMac:
        # compute the hash computed on values with the one stored
        # in the file. If they match, all is well.
        if not ('mac' in branch['sops']):
            raise AirflowException("SOPS decrypt error: 'mac' not found, unable to verify file integrity")
        h = digest.hexdigest().upper()
        # We know the original hash is trustworthy because it is encrypted
        # with the data key and authenticated using the lastmodified timestamp
        orig_h = _decrypt(branch['sops']['mac'], key,
                          aad=branch['sops']['lastmodified'].encode('utf-8'))
        if h != orig_h:
            raise AirflowException("SOPS decrypt error: Checksum verification failed!\nexpected {}\nbut got  {}}"
                                   .format(orig_h, h))

    return branch


def _decrypt(value, key, aad=b'', stash=None, digest=None, unencrypted=False):
    """Return a decrypted value."""
    if unencrypted:
        if digest:
            bvalue = _to_bytes(value)
            digest.update(bvalue)
        return value

    valre = b'^ENC\[AES256_GCM,data:(.+),iv:(.+),tag:(.+)'  # noqa: W605
    # extract fields using a regex
    if _a_is_newer_than_b(SOPS_INPUT_VERSION, '0.8'):
        valre += b',type:(.+)'
    valre += b'\]'  # noqa: W605
    res = re.match(valre, value.encode('utf-8'))
    # if the value isn't in encrypted form, return it as is
    if res is None:
        return value
    enc_value = b64decode(res.group(1))
    iv = b64decode(res.group(2))
    tag = b64decode(res.group(3))
    valtype = 'str'
    if _a_is_newer_than_b(SOPS_INPUT_VERSION, '0.8'):
        valtype = res.group(4)
    decryptor = Cipher(algorithms.AES(key),
                       modes.GCM(iv, tag),
                       default_backend()
                       ).decryptor()
    decryptor.authenticate_additional_data(aad)
    cleartext = decryptor.update(enc_value) + decryptor.finalize()

    if stash:
        # save the values for later if we need to reencrypt
        stash['iv'] = iv
        stash['aad'] = aad
        stash['cleartext'] = cleartext

    if digest:
        digest.update(cleartext)

    if valtype == b'bytes':
        return cleartext
    if valtype == b'str':
        # Welcome to python compatibility hell... :(
        # Python 2 treats everything as str, but python 3 treats bytes and str
        # as different types. So if a file was encrypted by sops with py2, and
        # contains bytes data, it will have type 'str' and py3 will decode
        # it as utf-8. This will result in a UnicodeDecodeError exception
        # because random bytes are not unicode. So the little try block below
        # catches it and returns the raw bytes if the value isn't unicode.
        cv = cleartext
        try:
            cv = cleartext.decode('utf-8')
        except UnicodeDecodeError:
            return cleartext
        return cv
    if valtype == b'int':
        return int(cleartext.decode('utf-8'))
    if valtype == b'float':
        return float(cleartext.decode('utf-8'))
    if valtype == b'bool':
        if cleartext.lower() == b'true':
            return True
        return False
    raise AirflowException("SOPS decrypt error: unknown type " + valtype)


def _set_gpg_exec(exec_name=None):
    """Sets the name of the GPG binary to use for PGP.
    If no exec_name is specified, use the SOPS_GPG_EXEC environment variable.
    Failing that, default to 'gpg'"""
    global GPG_EXEC

    if exec_name is not None:
        GPG_EXEC = exec_name
    else:
        GPG_EXEC = environ.get('SOPS_GPG_EXEC', 'gpg')


def _to_bytes(value):
    if not isinstance(value, bytes):
        # if not bytes, convert to bytes
        return str(value).encode('utf-8')
    return value


def _a_is_newer_than_b(A, B):
    # semver comparison of two version strings
    A_comp = str(A).split('.')
    B_comp = str(B).split('.')
    lim = len(A_comp)
    if len(B_comp) < lim:
        lim = len(B_comp)
    is_equal = True
    # Compare each component of the semver and if
    # A is greated than B, return true
    for i in range(0, lim):
        if int(A_comp[i]) > int(B_comp[i]):
            return True
        if int(A_comp[i]) != int(B_comp[i]):
            is_equal = False
    # If the versions are equal but A has more components
    # than B, A is considered newer (eg. 1.1.2 vs 1.1)
    if is_equal and len(A_comp) > len(B_comp):
        return True
    return False
