from django.forms.fields import BooleanField
from django.utils.translation import ugettext_lazy as _

import mock
from nose.tools import eq_

import amo
import amo.tests
from files.models import FileUpload
from users.models import UserProfile

from mkt.constants.features import APP_FEATURES
from mkt.site.fixtures import fixture
from mkt.submit import forms
from mkt.webapps.models import AppFeatures


class TestNewWebappForm(amo.tests.TestCase):

    def setUp(self):
        self.file = FileUpload.objects.create(valid=True)

    def test_not_free_or_paid(self):
        form = forms.NewWebappForm({})
        assert not form.is_valid()
        eq_(form.ERRORS['none'], form.errors['free_platforms'])
        eq_(form.ERRORS['none'], form.errors['paid_platforms'])

    def test_not_paid(self):
        form = forms.NewWebappForm({'paid_platforms': ['paid-firefoxos']})
        assert not form.is_valid()
        eq_(form.ERRORS['none'], form.errors['free_platforms'])
        eq_(form.ERRORS['none'], form.errors['paid_platforms'])

    def test_paid(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid_platforms': ['paid-firefoxos'],
                                    'upload': self.file.uuid})
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_PREMIUM)

    def test_free(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid})
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_FREE)

    def test_platform(self):
        self.create_switch('allow-b2g-paid-submission')
        mappings = (
            ({'free_platforms': ['free-firefoxos']}, [amo.DEVICE_GAIA]),
            ({'paid_platforms': ['paid-firefoxos']}, [amo.DEVICE_GAIA]),
            ({'free_platforms': ['free-firefoxos',
                                 'free-android-mobile']},
             [amo.DEVICE_GAIA, amo.DEVICE_MOBILE]),
            ({'free_platforms': ['free-android-mobile',
                                 'free-android-tablet']},
             [amo.DEVICE_MOBILE, amo.DEVICE_TABLET]),
        )
        for data, res in mappings:
            data['upload'] = self.file.uuid
            form = forms.NewWebappForm(data)
            assert form.is_valid(), form.errors
            self.assertSetEqual(res, form.get_devices())

    def test_both(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid_platforms': ['paid-firefoxos'],
                                    'free_platforms': ['free-firefoxos']})
        assert not form.is_valid()
        eq_(form.ERRORS['both'], form.errors['free_platforms'])
        eq_(form.ERRORS['both'], form.errors['paid_platforms'])

    def test_multiple(self):
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos',
                                                       'free-desktop'],
                                    'upload': self.file.uuid})
        assert form.is_valid()

    def test_not_packaged(self):
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid})
        assert form.is_valid(), form.errors
        assert not form.is_packaged()

    def test_not_packaged_allowed(self):
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid})
        assert form.is_valid(), form.errors
        assert not form.is_packaged()

    @mock.patch('mkt.submit.forms.parse_addon')
    def test_packaged_allowed(self, parse_addon):
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert form.is_valid(), form.errors
        assert form.is_packaged()

    @mock.patch('mkt.submit.forms.parse_addon')
    def test_packaged_allowed_android(self, parse_addon):
        form = forms.NewWebappForm({'free_platforms': ['free-android-mobile'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert form.is_valid(), form.errors
        assert form.is_packaged()

    @mock.patch('mkt.submit.forms.parse_addon',
                lambda *args: {'version': None})
    def test_packaged_wrong_device(self):
        form = forms.NewWebappForm({'free_platforms': ['free-desktop'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert not form.is_valid(), form.errors
        eq_(form.ERRORS['packaged'], form.errors['paid_platforms'])


class TestAppDetailsBasicForm(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def test_prefill_support_email(self):
        request = mock.Mock()
        request.amo_user = UserProfile.objects.get(id=999)
        form = forms.AppDetailsBasicForm({}, request=request)
        eq_(form.initial, {'support_email': {'en-us': 'regular@mozilla.com'}})


class TestAppFeaturesForm(amo.tests.TestCase):

    def setUp(self):
        self.form = forms.AppFeaturesForm()
        self.create_switch('buchets')

    def test_required(self):
        f_names = self.form.fields.keys()
        for value in (True, False):
            form = forms.AppFeaturesForm(dict((n, value) for n in f_names))
            eq_(form.is_valid(), True, form.errors)

    def test_correct_fields(self):
        fields = self.form.fields
        f_values = fields.values()
        assert 'version' not in fields
        assert all(isinstance(f, BooleanField) for f in f_values)
        self.assertSetEqual(fields, AppFeatures()._fields())

    def test_required_api_fields(self):
        fields = [f.help_text for f in self.form.required_api_fields()]
        eq_(fields, sorted(f[1] for f in APP_FEATURES))

    def test_required_api_fields_nonascii(self):
        forms.AppFeaturesForm.base_fields['has_apps'].help_text = _(u'H\xe9llo')
        fields = [f.help_text for f in self.form.required_api_fields()]
        eq_(fields, sorted(f[1] for f in APP_FEATURES))
