from django.forms import ModelForm

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase
from olympia.translations import fields, forms
from olympia.translations.tests.testapp.models import TranslatedModel


class DummyForm(forms.TranslationFormMixin, ModelForm):
    name = fields.TransField()

    class Meta:
        model = TranslatedModel
        fields = '__all__'


class TestTranslationFormMixin(TestCase):

    def test_default_locale(self):
        obj = TranslatedModel()
        obj.get_fallback = lambda: 'pl'

        f = DummyForm(instance=obj)
        assert f.fields['name'].default_locale == 'pl'
        assert f.fields['name'].widget.default_locale == 'pl'
        assert pq(f.as_p())('#id_name_0').attr('lang') == 'pl'

    def test_error_display(self):
        form = DummyForm(data={})
        # Both name and default_locale should display errors as lists with no
        # issues. Nothing about the underlying implementation should be shown
        # (i.e., don't display an ugly [u'This field is required'] message).
        # name is a translated field so data-lang is present.
        expected = (
            '<ul class="errorlist">'
            '<li data-lang="en-us">This field is required.</li>'
            '</ul>')
        assert form.errors['name'].as_ul() == expected
        # default_locale is a normal field so data-lang is absent.
        expected = (
            '<ul class="errorlist">'
            '<li>This field is required.</li>'
            '</ul>')
        assert form.errors['default_locale'].as_ul() == expected

        # When there are multiple errors, they should all be shown.
        form.add_error('name', 'Error message about name')
        form.add_error('default_locale', 'Error message about default_locale')
        expected = (
            '<ul class="errorlist">'
            '<li data-lang="en-us">This field is required.</li>'
            '<li>Error message about name</li>'
            '</ul>')
        assert form.errors['name'].as_ul() == expected
        expected = (
            '<ul class="errorlist">'
            '<li>This field is required.</li>'
            '<li>Error message about default_locale</li>'
            '</ul>')
        assert form.errors['default_locale'].as_ul() == expected
