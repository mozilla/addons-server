#!/usr/bin/env python
# Note: since this script appends stuff to the .po files, run it before
# locale/omg_new_l10n.sh - otherwise you'll need to merge translations
# yourself...

import json
import os

translations_dump = {}
translations_reordered = {}


def to_locale(language):
    """
    Turns a language name (en-us) into a locale name (en_US). If 'to_lower' is
    True, the last component is lower-cased (en_us).
    """
    p = language.find('-')
    if p >= 0:
        # Get correct locale for sr-latn
        if len(language[p + 1:]) > 2:
            return (language[:p].lower() + '_' + language[p + 1].upper() +
                    language[p + 2:].lower())
        return language[:p].lower() + '_' + language[p + 1:].upper()
    else:
        return language.lower()


def write_po(filename, translations_for_this_locale):
    with open(filename, 'a') as f:
        for msgid, msgstr in translations_for_this_locale.items():
            f.write('\n')
            # Note: not including the line number, that will mess up the first
            # diff for translations coming back from pontoon, but since the
            # .po file is also going to be re-orderered (this script only
            # appends stuff at the end) that does not matter much...
            f.write('#: /src/olympia/constants/categories.py\n')
            f.write('msgid "%s"\n' % msgid)
            f.write('msgstr "%s"\n' % msgstr.encode('utf-8'))


def extract_translations_for_given_locale(all_translations, locale):
    # Inefficient but we don't really care for a one-shot script.
    translations = {}
    locale = to_locale(locale)
    for msg, msg_translations in all_translations.items():
        if locale in msg_translations:
            translations[msg] = msg_translations[locale]
    return translations


def main():
    if not os.path.isdir('locale'):
        print ('Sorry, please run from the root of the project, '
               'eg. ./locale/generate_category_po_files.py')
        return

    print('Loading translations JSON dump...')
    all_translations = json.load(open('./locale/category_translations.json'))

    for locale in os.listdir('./locale/'):
        directory = os.path.join('./locale', locale)
        if not os.path.isdir(directory) or locale == 'templates':
            # print "Skipping %s since it's not a locale directory" % locale
            continue

        fname = os.path.join(directory, 'LC_MESSAGES', 'django.po')
        if not os.path.exists(fname):
            print("Skipping %s since it doesn't contain a django.po file")
            continue

        translations_for_this_locale = extract_translations_for_given_locale(
            all_translations, locale)

        if not translations_for_this_locale:
            print('Skipping locale %s, it has no translations :(' % locale)
            continue

        print("Writing %d translations to %s" % (
            len(translations_for_this_locale), fname))
        write_po(fname, translations_for_this_locale)


if __name__ == '__main__':
    main()
