import base64
import os


__all__ = ['generate_key']


def generate_key(byte_length):
    """Return a true random ascii string that is byte_length long.

    The resulting key is suitable for cryptogrpahy.
    """
    if byte_length < 32:  # at least 256 bit
        raise ValueError('um, %s is probably not long enough for cryptography'
                         % byte_length)
    key = os.urandom(byte_length)
    key = base64.b64encode(key).rstrip('=')  # strip off padding
    key = key[0:byte_length]
    return key
