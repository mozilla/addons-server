from pyquery import PyQuery as pq
from nose.tools import eq_

from django.forms import ModelForm

import amo.tests
from translations import forms, fields
from translations.tests.testapp.models import TranslatedModel


class TestForm(forms.TranslationFormMixin, ModelForm):
    name = fields.TransField()
    class Meta:
        model = TranslatedModel


class TestTranslationFormMixin(amo.tests.TestCase):

    def test_default_locale(self):
        obj = TranslatedModel()
        obj.get_fallback = lambda: 'pl'

        f = TestForm(instance=obj)
        eq_(f.fields['name'].default_locale, 'pl')
        eq_(f.fields['name'].widget.default_locale, 'pl')
        eq_(pq(f.as_p())('input:not([lang=init])').attr('lang'), 'pl')
