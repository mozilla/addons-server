import test_utils
from nose.tools import eq_

from redisutils import mock_redis, reset_redis
from addons import forms, cron
from addons.models import Addon


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
