"""Tests for the jingo's builtin helpers."""
from datetime import datetime

from nose.tools import eq_

import jingo


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_f():
    s = render('{{ "{0} : {z}"|f("a", z="b") }}')
    eq_(s, 'a : b')


def test_nl2br():
    text = "some\ntext\n\nwith\nnewlines"
    s = render('{{ x|nl2br }}', {'x': text})
    eq_(s, "some<br>text<br><br>with<br>newlines")


def test_datetime():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|datetime }}', {'d': time})
    eq_(s, 'December 25, 2009')

    s = render('{{ d|datetime("%Y-%m-%d %H:%M:%S") }}', {'d': time})
    eq_(s, '2009-12-25 10:11:12')


def test_ifeq():
    eq_context = {'a': 1, 'b': 1}
    neq_context = {'a': 1, 'b': 2}

    s = render('{{ a|ifeq(b, "<b>something</b>") }}', eq_context)
    eq_(s, '<b>something</b>')

    s = render('{{ a|ifeq(b, "<b>something</b>") }}', neq_context)
    eq_(s, '')


def test_class_selected():
    eq_context = {'a': 1, 'b': 1}
    neq_context = {'a': 1, 'b': 2}

    s = render('{{ a|class_selected(b) }}', eq_context)
    eq_(s, 'class="selected"')

    s = render('{{ a|class_selected(b) }}', neq_context)
    eq_(s, '')


def test_csrf():
    s = render('{{ csrf() }}', {'csrf_token': 'fffuuu'})
    eq_(s, "<div style='display:none'>"
           "<input type='hidden' name='csrfmiddlewaretoken' value='fffuuu' />"
           "</div>")
