#!/usr/bin/env python3
import datetime
import os
import string
import sys
import unicodedata

import django


if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
    django.setup()

    from olympia.amo.confusables import additional_character_replacements
    from olympia.amo.utils import generate_lowercase_homoglyphs_variants_for_string
    from olympia.amo.validators import OneOrMorePrintableCharacterValidator

    new = {}
    start = datetime.datetime.now()

    # Like build_characters_normalization_replacement_table(), but without the
    # additional_character_replacements dict.
    # care about).
    translations_table = dict.fromkeys(
        i
        for i in range(sys.maxunicode)
        if unicodedata.category(chr(i))[0] in ('Z', 'P', 'M', 'C', 'S')
        or chr(i) in OneOrMorePrintableCharacterValidator.special_blank_characters
    )

    seen = set()
    # Our table only normalizes, so it's a 1:1 character replacement that should
    # not have duplicates. We check for dupes in reverse alphabetical order because
    # we prefer normalizing characters that are confused with 't' over 'l', and 'l'
    # over 'i'.
    for letter in string.ascii_letters[:26][::-1]:
        # Check for confusables already known by homoglyph_fork or normalize().
        for character in additional_character_replacements[letter]:
            normalized = unicodedata.normalize('NFKD', str(character))
            normalized = normalized.translate(translations_table)
            variants = list(
                generate_lowercase_homoglyphs_variants_for_string(normalized)
            )
            assert letter not in variants, (
                f'{letter} had {character} which is already considered confusable'
            )
        # Check for confusables already seen elsewhere in the dict.
        for_this_letter = set(additional_character_replacements[letter])
        in_common = for_this_letter.intersection(seen)
        assert in_common == set(), (
            f'{letter} had confusables already seen elsewhere: {in_common}'
        )
        seen.update(for_this_letter)

    elapsed = int((datetime.datetime.now() - start).total_seconds())
    print(f'Checked {len(seen)} additional confusables in {elapsed} seconds.')
