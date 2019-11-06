import codecs
import re

UNICODE_BOMS = [
    (codecs.BOM_UTF8, 'utf-8'),
    (codecs.BOM_UTF32_LE, 'utf-32-le'),
    (codecs.BOM_UTF32_BE, 'utf-32-be'),
    (codecs.BOM_UTF16_LE, 'utf-16-le'),
    (codecs.BOM_UTF16_BE, 'utf-16-be'),
]

COMMON_ENCODINGS = ('latin_1', 'utf-16')

# Matches any non-ASCII characters, and any unprintable characters in the
# 7-bit ASCII range. Accepts tab, return, newline, and any other character
# code above 0x20 which fits in 7 bits.
NON_ASCII_FILTER = re.compile(r'[^\t\r\n\x20-\x7f]+')


def decode(data):
    """
    Decode data employing some charset detection and including unicode BOM
    stripping.
    """

    if isinstance(data, str):
        return data

    # Detect standard unicode BOMs.
    for bom, encoding in UNICODE_BOMS:
        if data.startswith(bom):
            return data[len(bom) :].decode(encoding, errors='ignore')

    # Try straight UTF-8.
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass

    # Test for various common encodings.
    for encoding in COMMON_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    # Anything else gets filtered.
    return NON_ASCII_FILTER.sub('', data).decode('ascii', errors='replace')
