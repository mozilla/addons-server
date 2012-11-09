import mock
from nose.tools import eq_

import amo
import amo.tests
from files.models import FileUpload
from mkt.submit import forms


class TestNewWebappForm(amo.tests.TestCase):

    def setUp(self):
        self.file = FileUpload.objects.create(valid=True)

    def test_not_free_or_paid(self):
        form = forms.NewWebappForm({})
        assert not form.is_valid()
        eq_(form.ERRORS['none'], form.errors['free'])
        eq_(form.ERRORS['none'], form.errors['paid'])

    def test_not_paid(self):
        form = forms.NewWebappForm({'paid': ['paid-os']})
        assert not form.is_valid()
        eq_(form.ERRORS['none'], form.errors['free'])
        eq_(form.ERRORS['none'], form.errors['paid'])

    def test_paid(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid': ['paid-os'],
                                    'upload': self.file.uuid})
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_PREMIUM)

    def test_free(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'free': ['free-os'],
                                    'upload': self.file.uuid})
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_FREE)

    def test_platform(self):
        self.create_switch('allow-b2g-paid-submission')
        for data, res in (
                ({'free': ['free-os']}, [amo.DEVICE_GAIA]),
                ({'paid': ['paid-os']}, [amo.DEVICE_GAIA]),
                ({'free': ['free-os', 'free-phone']},
                 [amo.DEVICE_GAIA, amo.DEVICE_MOBILE]),
                ({'free': ['free-phone', 'free-tablet']},
                 [amo.DEVICE_MOBILE, amo.DEVICE_TABLET]),
            ):
            data['upload'] = self.file.uuid
            form = forms.NewWebappForm(data)
            assert form.is_valid(), form.errors
            self.assertSetEqual(res, form.get_devices())

    def test_both(self):
        self.create_switch('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid': ['paid-os'],
                                    'free': ['free-os']})
        assert not form.is_valid()
        eq_(form.ERRORS['both'], form.errors['free'])
        eq_(form.ERRORS['both'], form.errors['paid'])

    def test_multiple(self):
        form = forms.NewWebappForm({'free': ['free-os',
                                             'free-desktop'],
                                    'upload': self.file.uuid})
        assert form.is_valid()

    def test_not_packaged(self):
        form = forms.NewWebappForm({'free': ['free-os'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert form.is_valid(), form.errors
        assert not form.is_packaged()

    def test_not_packaged_allowed(self):
        self.create_switch('allow-packaged-app-uploads')
        form = forms.NewWebappForm({'free': ['free-os'],
                                    'upload': self.file.uuid})
        assert form.is_valid(), form.errors
        assert not form.is_packaged()

    @mock.patch('mkt.submit.forms.parse_addon')
    def test_packaged_allowed(self, parse_addon):
        self.create_switch('allow-packaged-app-uploads')
        form = forms.NewWebappForm({'free': ['free-os'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert form.is_valid()
        assert form.is_packaged()

    def test_packaged_wrong_device(self):
        self.create_switch('allow-packaged-app-uploads')
        form = forms.NewWebappForm({'free': ['free-desktop'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert not form.is_valid(), form.errors
        eq_(form.ERRORS['packaged'], form.errors['paid'])
