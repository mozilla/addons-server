import os
import base64
import shutil
from cStringIO import StringIO

from django.utils import translation

import jingo

from nose import with_setup
from nose.tools import eq_

import l10n
from l10n.tests.helpers import fake_extract_from_dir
from l10n import ugettext as _, ungettext as n_
from l10n import ugettext_lazy as _lazy, ungettext_lazy as n_lazy
from l10n.management.commands.extract import create_pofile_from_babel

LOCALEDIR = os.path.join('locale', 'xx')
MOFILE = os.path.join(LOCALEDIR, 'LC_MESSAGES', 'messages.mo')

# Used for the _lazy() tests
_lazy_strings = {}
_lazy_strings['nocontext'] = _lazy('this is a test')
_lazy_strings['context'] = _lazy('What time is it?', 'context_one')

n_lazy_strings = {}
n_lazy_strings['s_nocontext'] = n_lazy('one light !', 'many lights !', 1)
n_lazy_strings['p_nocontext'] = n_lazy('one light !', 'many lights !', 3)
n_lazy_strings['s_context'] = n_lazy('%d poodle please', '%d poodles please',
                                     1, 'context_one')
n_lazy_strings['p_context'] = n_lazy('%d poodle please', '%d poodles please',
                                     3, 'context_one')


# Stolen from jingo's test_helpers
def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


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
    l10n.deactivate_all()


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
def test_ugettext_not_found():
    eq_('yo', _('yo'))
    eq_('yo yo', _('  yo  yo  '))
    eq_('yo', _('yo', 'context'))
    eq_('yo yo', _('  yo  yo  ', 'context'))


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


@with_setup(setup, teardown)
def test_ungettext_not_found():
    eq_('yo', n_('yo', 'yos', 1, 'context'))
    eq_('yo yo', n_('  yo  yo  ', 'yos', 1, 'context'))
    eq_('yos', n_('yo', 'yos', 3, 'context'))
    eq_('yo yos', n_('yo', '  yo  yos  ', 3, 'context'))


@with_setup(setup, teardown)
def test_ugettext_lazy():
    eq_(unicode(_lazy_strings['nocontext']), 'you ran a test!')
    eq_(unicode(_lazy_strings['context']), 'What time is it? (context=1)')


@with_setup(setup, teardown)
def test_ungettext_lazy():
    eq_(unicode(n_lazy_strings['s_nocontext']), 'you found a light!')
    eq_(unicode(n_lazy_strings['p_nocontext']), 'you found a pile of lights!')
    eq_(unicode(n_lazy_strings['s_context']), '%d poodle (context=1)')
    eq_(unicode(n_lazy_strings['p_context']), '%d poodles (context=1)')


def test_add_context():
    eq_("nacho\x04testo", l10n.add_context("nacho", "testo"))


def test_split_context():
    eq_(["", u"testo"], l10n.split_context("testo"))
    eq_([u"nacho", u"testo"], l10n.split_context("nacho\x04testo"))


def test_activate():
    l10n.deactivate_all()
    l10n.activate('fr')
    # This string is from the AMO .po file
    a_text = "My Account"
    p_text = "Mon compte"
    eq_(p_text, _(a_text))
    l10n.deactivate_all()


def test_cached_activate():
    """
    Make sure the locale is always activated properly, even when we hit a
    cached version.
    """
    l10n.deactivate_all()
    l10n.activate('fr')
    eq_(translation.get_language(), 'fr')
    l10n.activate('vi')
    eq_(translation.get_language(), 'vi')
    l10n.activate('fr')
    eq_(translation.get_language(), 'fr')
    l10n.activate('de')
    eq_(translation.get_language(), 'de')
    l10n.activate('fr')
    eq_(translation.get_language(), 'fr')
    l10n.activate('vi')
    eq_(translation.get_language(), 'vi')


@with_setup(setup, teardown)
def test_template_simple():
    s = '{% trans %}this is a test{% endtrans %}'
    eq_(render(s), 'you ran a test!')

    s = '''{% trans %}
        this
        is
        a
        test
        {% endtrans %}'''
    eq_(render(s), 'you ran a test!')


@with_setup(setup, teardown)
def test_template_substitution():
    s = '{% trans user="wenzel" %} Hello {{ user }}{% endtrans %}'
    eq_(render(s), 'Hola wenzel')

    s = '''{% trans user="wenzel" %}
            Hello
            \t\r\n
            {{ user }}
            {% endtrans %}'''
    eq_(render(s), 'Hola wenzel')


@with_setup(setup, teardown)
def test_template_gettext_functions():
    s = '{{ _("yy", "context") }}'
    eq_(render(s), 'yy')

    s = '{{ gettext("yy", "context") }}'
    eq_(render(s), 'yy')

    s = '{{ ngettext("1", "2", 1, "context") }}'
    eq_(render(s), '1')


def test_extract_amo_python():
    fileobj = StringIO(TEST_PO_INPUT)
    method = 'l10n.management.commands.extract.extract_amo_python'
    output = fake_extract_from_dir(filename="filename", fileobj=fileobj,
                                   method=method)

    # god help you if these are ever unequal
    eq_(TEST_PO_OUTPUT, unicode(create_pofile_from_babel(output)))


def test_extract_amo_template():
    fileobj = StringIO(TEST_TEMPLATE_INPUT)
    method = 'l10n.management.commands.extract.extract_amo_template'
    output = fake_extract_from_dir(filename="filename", fileobj=fileobj,
                                   method=method)

    # god help you if these are ever unequal
    eq_(TEST_TEMPLATE_OUTPUT, unicode(create_pofile_from_babel(output)))


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

TEST_PO_INPUT = """
# Make sure multiple contexts stay separate
_('fligtar')
_('fligtar', 'atwork')
_('fligtar', 'athome')

# Test regular plural form, no context
ngettext('a fligtar', 'many fligtars', 3)

# Make sure several uses collapses to one
ngettext('a fligtar', 'many fligtars', 1, 'aticecreamshop')
ngettext('a fligtar', 'many fligtars', 3, 'aticecreamshop')
ngettext('a fligtar', 'many fligtars', 5, 'aticecreamshop')

# Test comments
# L10n: Turn up the volume
_('fligtar    \n\n\r\t  talking')

# Test comments w/ plural and context
# L10n: Turn down the volume
ngettext('fligtar', 'many fligtars', 5, 'aticecreamshop')
"""

TEST_PO_OUTPUT = """\
#: filename:3
msgid "fligtar"
msgstr ""

#: filename:4
msgctxt "atwork"
msgid "fligtar"
msgstr ""

#: filename:5
msgctxt "athome"
msgid "fligtar"
msgstr ""

#: filename:8
msgid "a fligtar"
msgid_plural "many fligtars"
msgstr[0] ""

#: filename:11
#: filename:12
#: filename:13
msgctxt "aticecreamshop"
msgid "a fligtar"
msgid_plural "many fligtars"
msgstr[0] ""

#. L10n: Turn down the volume
#: filename:23
msgctxt "aticecreamshop"
msgid "fligtar"
msgid_plural "many fligtars"
msgstr[0] ""
"""

TEST_TEMPLATE_INPUT = """
  {{ _('sunshine') }}
  {{ _('sunshine', 'nothere') }}
  {{ _('sunshine', 'outside') }}

  {# Regular comment, regular gettext #}
  {% trans %}
    I like pie.
  {% endtrans %}

  {# L10n: How many hours? #}
  {% trans plural=4, count=4 %}
    {{ count }} hour left
  {% pluralize %}
    {{ count }} hours left
  {% endtrans %}

  {{ ngettext("one", "many", 5) }}

  {# L10n: This string has a hat. #}
  {% trans %}
  Let me tell you about a string
  who spanned
  multiple lines.
  {% endtrans %}
"""

TEST_TEMPLATE_OUTPUT = """\
#: filename:2
msgid "sunshine"
msgstr ""

#: filename:3
msgctxt "nothere"
msgid "sunshine"
msgstr ""

#: filename:4
msgctxt "outside"
msgid "sunshine"
msgstr ""

#: filename:7
msgid "I like pie."
msgstr ""

#. How many hours?
#: filename:12
msgid "%(count)s hour left"
msgid_plural "%(count)s hours left"
msgstr[0] ""

#: filename:18
msgid "one"
msgid_plural "many"
msgstr[0] ""

#. This string has a hat.
#: filename:21
msgid "Let me tell you about a string who spanned multiple lines."
msgstr ""
"""
