import os


__all__ = ['generate_key']


def generate_key(byte_length):
    """Return a true random ascii string containing byte_length of randomness.

    The resulting key is suitable for cryptogrpahy.
    The key will be hex encoded which means it will be twice as long
    as byte_length, i.e. 40 random bytes yields an 80 byte string.

    byte_length must be at least 32.
    """
    if byte_length < 32:  # at least 256 bit
        raise ValueError('um, %s is probably not long enough for cryptography'
                         % byte_length)
    return os.urandom(byte_length).encode('hex')
