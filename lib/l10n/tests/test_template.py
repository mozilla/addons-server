from nose import with_setup
from nose.tools import eq_

import jingo

from tests import setup, teardown


# Stolen from jingo's test_helpers
def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


@with_setup(setup, teardown)
def test_simple():
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
def test_substitution():
    s = '{% trans user="wenzel" %} Hello {{ user }}{% endtrans %}'
    eq_(render(s), 'Hola wenzel')

    s = '''{% trans user="wenzel" %}
            Hello
            \t\r\n
            {{ user }}
            {% endtrans %}'''
    eq_(render(s), 'Hola wenzel')


@with_setup(setup, teardown)
def test_gettext_functions():
    s = '{{ _("yy", "context") }}'
    eq_(render(s), 'yy')

    s = '{{ gettext("yy", "context") }}'
    eq_(render(s), 'yy')

    s = '{{ ngettext("1", "2", 1, "context") }}'
    eq_(render(s), '1')
