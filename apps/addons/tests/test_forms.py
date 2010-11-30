import test_utils
from nose.tools import eq_

from redisutils import mock_redis, reset_redis
from addons import forms, cron
from addons.models import Addon
from addons.forms import AddonFormDetails
import amo


class FormsTest(test_utils.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        self._redis = mock_redis()
        cron.build_reverse_name_lookup()
        self.existing_name = 'Delicious Bookmarks'
        self.error_msg = ('This add-on name is already in use. '
                          'Please choose another.')

    def tearDown(self):
        reset_redis(self._redis)

    def test_new(self):
        """
        New add-ons shouldn't be able to use existing add-on names.
        """
        f = forms.AddonForm(dict(name=self.existing_name))
        assert not f.is_valid()
        eq_(f.errors['name'][0], self.error_msg)

    def test_old(self):
        """
        Exiting add-ons shouldn't be able to use someone else's name.
        """
        a = Addon.objects.create(type=1)
        f = forms.AddonFormBasic(dict(name=self.existing_name), request=None,
                                 instance=a)
        assert not f.is_valid()
        eq_(f.errors.get('name')[0][1], self.error_msg)

    def test_old_same(self):
        """
        Exiting add-ons should be able to re-use their name.
        """
        delicious = Addon.objects.get()
        f = forms.AddonFormBasic(dict(name=self.existing_name), request=None,
                                 instance=delicious)
        eq_(f.errors.get('name'), None)

    def test_locales(self):
        form = AddonFormDetails(request={})
        eq_(form.fields['default_locale'].choices[0][0], 'af')


class TestUpdate(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'base/platforms',
                'base/appversion']

    def setUp(self):
        self.good_data = {
            'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'version': '2.0.58',
            'reqVersion': 1,
            'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'appVersion': '3.7a1pre'
        }

    def test_beta(self):
        data = self.good_data.copy()
        for good in ['1.0a', '1.0beta2', '1.0 beta2']:
            data['version'] = good
            form = forms.UpdateForm(data)
            assert form.is_valid()
            assert form.is_beta_version

        for bad in ['1.0', 'beta 1.0', '1.0 beta 2']:
            data['version'] = bad
            form = forms.UpdateForm(data)
            assert form.is_valid()
            assert not form.is_beta_version

    def test_app_os(self):
        data = self.good_data.copy()
        data['appOS'] = 'something %s penguin' % amo.PLATFORM_LINUX.shortname
        form = forms.UpdateForm(data)
        assert form.is_valid()
        eq_(form.cleaned_data['appOS'], amo.PLATFORM_LINUX)

    def test_app_version_fails(self):
        data = self.good_data.copy()
        del data['appID']
        form = forms.UpdateForm(data)
        assert not form.is_valid()

    def test_app_version_wrong(self):
        data = self.good_data.copy()
        data['appVersion'] = '67.7'
        form = forms.UpdateForm(data)
        # If you pass through the wrong version that's fine
        # you will just end up with no updates because your
        # version_int will be out.
        assert form.is_valid()

    def test_app_version(self):
        data = self.good_data.copy()
        form = forms.UpdateForm(data)
        assert form.is_valid()
        eq_(form.version_int, 3070000001000)
