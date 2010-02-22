import os
import base64
import shutil

from nose import with_setup
from nose.tools import eq_

import l10n
from l10n import ugettext as _, ungettext as n_

LOCALEDIR = os.path.join('locale', 'xx')
MOFILE = os.path.join(LOCALEDIR, 'LC_MESSAGES', 'messages.mo')


def setup():
    if not os.path.isdir(os.path.join(LOCALEDIR, 'LC_MESSAGES')):
        os.makedirs(os.path.join(LOCALEDIR, 'LC_MESSAGES'))
    fp = open(MOFILE, 'wb')
    fp.write(base64.decodestring(MO_DATA))
    fp.close()

    l10n.activate('xx')


def teardown():
    if os.path.isdir(LOCALEDIR):
        shutil.rmtree(LOCALEDIR)


@with_setup(setup, teardown)
def test_ugettext():
    # No context
    a_text = " this\t\r\n\nis    a\ntest  \n\n\n"
    p_text = "you ran a test!"
    eq_(p_text, _(a_text))

    # With a context
    a_text = "\n\tWhat time \r\nis it?  \n"
    p_text_1 = "What time is it? (context=1)"
    p_text_2 = "What time is it? (context=2)"
    eq_(p_text_1, _(a_text, 'context_one'))
    eq_(p_text_2, _(a_text, 'context_two'))


@with_setup(setup, teardown)
def test_ungettext():
    # No context
    a_singular = " one\t\r\n\nlight \n\n!\n"
    a_plural = " many\t\r\n\nlights \n\n!\n"
    p_singular = "you found a light!"
    p_plural = "you found a pile of lights!"
    eq_(p_singular, n_(a_singular, a_plural, 1))
    eq_(p_plural, n_(a_singular, a_plural, 3))

    # With a context
    a_singular = "%d \n\n\tpoodle please"
    a_plural = "%d poodles\n\n\t please\n\n\n"
    p_singular_1 = "%d poodle (context=1)"
    p_plural_1 = "%d poodles (context=1)"
    p_singular_2 = "%d poodle (context=2)"
    p_plural_2 = "%d poodles (context=2)"
    eq_(p_singular_1, n_(a_singular, a_plural, 1, 'context_one'))
    eq_(p_plural_1, n_(a_singular, a_plural, 3, 'context_one'))
    eq_(p_singular_2, n_(a_singular, a_plural, 1, 'context_two'))
    eq_(p_plural_2, n_(a_singular, a_plural, 3, 'context_two'))


def test_activate():
    l10n.activate('fr')
    # This string is from the AMO .po file
    a_text = "My Account"
    p_text = "Mon compte"
    eq_(p_text, _(a_text))


MO_DATA = '''\
3hIElQAAAAAHAAAAHAAAAFQAAAALAAAAjAAAAA4AAAC4AAAALgAAAMcAAAAcAAAA9gAAAC4AAAAT
AQAAHAAAAEIBAAAZAAAAXwEAAA4AAAB5AQAADQAAAIgBAAAsAAAAlgEAABwAAADDAQAALAAAAOAB
AAAcAAAADQIAAC4AAAAqAgAADwAAAFkCAAACAAAAAAAAAAAAAAAFAAAABgAAAAMAAAAAAAAABAAA
AAAAAAABAAAABwAAAEhlbGxvICUodXNlcilzAGNvbnRleHRfb25lBCVkIHBvb2RsZSBwbGVhc2UA
JWQgcG9vZGxlcyBwbGVhc2UAY29udGV4dF9vbmUEV2hhdCB0aW1lIGlzIGl0PwBjb250ZXh0X3R3
bwQlZCBwb29kbGUgcGxlYXNlACVkIHBvb2RsZXMgcGxlYXNlAGNvbnRleHRfdHdvBFdoYXQgdGlt
ZSBpcyBpdD8Ab25lIGxpZ2h0ICEAbWFueSBsaWdodHMgIQB0aGlzIGlzIGEgdGVzdABIb2xhICUo
dXNlcilzACVkIHBvb2RsZSAoY29udGV4dD0xKQAlZCBwb29kbGVzIChjb250ZXh0PTEpAFdoYXQg
dGltZSBpcyBpdD8gKGNvbnRleHQ9MSkAJWQgcG9vZGxlIChjb250ZXh0PTIpACVkIHBvb2RsZXMg
KGNvbnRleHQ9MikAV2hhdCB0aW1lIGlzIGl0PyAoY29udGV4dD0yKQB5b3UgZm91bmQgYSBsaWdo
dCEAeW91IGZvdW5kIGEgcGlsZSBvZiBsaWdodHMhAHlvdSByYW4gYSB0ZXN0IQA=
'''

# MO_DATA was created with this data.  You can also run `msgunfmt filename`
'''
msgid "this is a test"
msgstr "you ran a test!"

# Here is a comment
#: some/file.py:157
msgid "one light !"
msgid_plural "many lights !"
msgstr[0] "you found a light!"
msgstr[1] "you found a pile of lights!"

msgctxt "context_one"
msgid "What time is it?"
msgstr "What time is it? (context=1)"

msgctxt "context_two"
msgid "What time is it?"
msgstr "What time is it? (context=2)"

# %d is the number of dogs
#: some/file.py:157
#, python-format
msgctxt "context_one"
msgid "%d poodle please"
msgid_plural "%d poodles please"
msgstr[0] "%d poodle (context=1)"
msgstr[1] "%d poodles (context=1)"

# %d is the number of dogs
#: some/file.py:157
#, python-format
msgctxt "context_two"
msgid "%d poodle please"
msgid_plural "%d poodles please"
msgstr[0] "%d poodle (context=2)"
msgstr[1] "%d poodles (context=2)"

#, python-format
msgid "Hello %(user)s"
msgstr "Hola %(user)s"
'''
