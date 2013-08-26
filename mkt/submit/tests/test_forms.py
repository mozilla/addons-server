from django.forms.fields import BooleanField
from django.utils.translation import ugettext_lazy as _

import mock
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo
import amo.tests
from devhub.models import AppLog
from editors.models import RereviewQueue
from files.models import FileUpload
from users.models import UserProfile

from mkt.constants.features import APP_FEATURES
from mkt.site.fixtures import fixture
from mkt.submit import forms
from mkt.webapps.models import AppFeatures, Webapp


class TestNewWebappForm(amo.tests.TestCase):

    def setUp(self):
        self.request = RequestFactory().get('/')
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
        self.create_flag('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid_platforms': ['paid-firefoxos'],
                                    'upload': self.file.uuid},
                                   request=self.request)
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_PREMIUM)

    def test_free(self):
        self.create_flag('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid})
        assert form.is_valid()
        eq_(form.get_paid(), amo.ADDON_FREE)

    def test_platform(self):
        self.create_flag('allow-b2g-paid-submission')
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
        self.create_flag('allow-b2g-paid-submission')
        form = forms.NewWebappForm({'paid_platforms': ['paid-firefoxos'],
                                    'free_platforms': ['free-firefoxos']},
                                   request=self.request)
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
        parse_addon.return_value = {}
        form = forms.NewWebappForm({'free_platforms': ['free-firefoxos'],
                                    'upload': self.file.uuid,
                                    'packaged': True})
        assert form.is_valid(), form.errors
        assert form.is_packaged()

    @mock.patch('mkt.submit.forms.parse_addon')
    def test_packaged_allowed_android(self, parse_addon):
        parse_addon.return_value = {}
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


class TestNewWebappVersionForm(amo.tests.TestCase):

    def setUp(self):
        self.request = RequestFactory().get('/')
        self.file = FileUpload.objects.create(valid=True)

    def test_no_upload(self):
        form = forms.NewWebappVersionForm(request=self.request,
                                          is_packaged=True)
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.submit.forms.parse_addon',
                lambda *args: {"origin": "app://hy.fr"})
    @mock.patch('mkt.submit.forms.verify_app_domain')
    def test_verify_app_domain_called(self, _verify):
        self.create_switch('webapps-unique-by-domain')
        form = forms.NewWebappVersionForm({'upload': self.file.uuid},
                                          request=self.request,
                                          is_packaged=True)
        assert form.is_valid(), form.errors
        assert _verify.called

    @mock.patch('mkt.submit.forms.parse_addon',
                lambda *args: {"origin": "app://hy.fr"})
    def test_verify_app_domain_exclude_same(self):
        app = amo.tests.app_factory(app_domain='app://hy.fr')
        form = forms.NewWebappVersionForm(
            {'upload': self.file.uuid}, request=self.request, is_packaged=True,
            addon=app)
        assert form.is_valid(), form.errors

    @mock.patch('mkt.submit.forms.parse_addon',
                lambda *args: {"origin": "app://hy.fr"})
    def test_verify_app_domain_exclude_different(self):
        app = amo.tests.app_factory(app_domain='app://yo.lo')
        amo.tests.app_factory(app_domain='app://hy.fr')
        form = forms.NewWebappVersionForm(
            {'upload': self.file.uuid}, request=self.request, is_packaged=True,
            addon=app)
        assert not form.is_valid(), form.errors
        assert 'An app already exists' in ''.join(form.errors['upload'])


class TestAppDetailsBasicForm(amo.tests.TestCase):
    fixtures = fixture('user_999', 'webapp_337141')

    def setUp(self):
        self.request = mock.Mock()
        self.request.amo_user = UserProfile.objects.get(id=999)

    def test_prefill_support_email(self):
        form = forms.AppDetailsBasicForm({}, request=self.request)
        eq_(form.initial, {'support_email': {'en-us': 'regular@mozilla.com'}})

    def test_slug(self):
        app = Webapp.objects.get(pk=337141)
        data = {
            'app_slug': 'thisIsAslug',
            'description': '.',
            'privacy_policy': '.',
            'support_email': 'test@example.com',
        }
        form = forms.AppDetailsBasicForm(data, request=self.request,
                                         instance=app)
        assert form.is_valid()
        form.save()
        app.reload()
        eq_(app.app_slug, 'thisisaslug')


class TestAppFeaturesForm(amo.tests.TestCase):
    fixtures = fixture('user_999', 'webapp_337141')

    def setUp(self):
        amo.set_user(UserProfile.objects.all()[0])
        self.form = forms.AppFeaturesForm()
        self.app = Webapp.objects.get(pk=337141)
        self.features = self.app.current_version.features
        self.create_switch('buchets')

    def _check_log(self, action):
        assert AppLog.objects.filter(
            addon=self.app, activity_log__action=action.id).exists(), (
                "Didn't find `%s` action in logs." % action.short)

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
        eq_(fields, sorted(f['name'] for f in APP_FEATURES.values()))

    def test_required_api_fields_nonascii(self):
        forms.AppFeaturesForm.base_fields['has_apps'].help_text = _(
            u'H\xe9llo')
        fields = [f.help_text for f in self.form.required_api_fields()]
        eq_(fields, sorted(f['name'] for f in APP_FEATURES.values()))

    def test_changes_mark_for_rereview(self):
        self.features.update(has_sms=True)
        data = {'has_apps': True}
        self.form = forms.AppFeaturesForm(instance=self.features, data=data)
        self.form.save()
        ok_(self.features.has_apps)
        ok_(not self.features.has_sms)
        ok_(not self.features.has_contacts)
        action_id = amo.LOG.REREVIEW_FEATURES_CHANGED.id
        assert AppLog.objects.filter(addon=self.app,
            activity_log__action=action_id).exists()
        eq_(RereviewQueue.objects.count(), 1)

    def test_no_changes_not_marked_for_rereview(self):
        self.features.update(has_sms=True)
        data = {'has_sms': True}
        self.form = forms.AppFeaturesForm(instance=self.features, data=data)
        self.form.save()
        ok_(not self.features.has_apps)
        ok_(self.features.has_sms)
        eq_(RereviewQueue.objects.count(), 0)
        action_id = amo.LOG.REREVIEW_FEATURES_CHANGED.id
        assert not AppLog.objects.filter(addon=self.app,
             activity_log__action=action_id).exists()

    def test_changes_mark_for_rereview_bypass(self):
        self.features.update(has_sms=True)
        data = {'has_apps': True}
        self.form = forms.AppFeaturesForm(instance=self.features, data=data)
        self.form.save(mark_for_rereview=False)
        ok_(self.features.has_apps)
        ok_(not self.features.has_sms)
        eq_(RereviewQueue.objects.count(), 0)
        action_id = amo.LOG.REREVIEW_FEATURES_CHANGED.id
        assert not AppLog.objects.filter(addon=self.app,
             activity_log__action=action_id).exists()
