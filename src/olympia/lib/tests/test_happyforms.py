from django import forms

from olympia.lib.happyforms import Form


class MyTestForm(Form):
    foo = forms.CharField()


def test_happyform_with_whitespace():
    form = MyTestForm(data={'foo': ' blah '})
    assert form.is_valid()
    assert form.clean() == {'foo': 'blah'}


def test_happyform_with_newlines():
    form = MyTestForm(data={'foo': '\n blah bar\n '})
    assert form.is_valid()
    assert form.clean() == {'foo': 'blah bar'}
