# -*- coding: utf-8 -*-
import os
import shutil
import tempfile

import test_utils
from nose.tools import eq_
from mock import patch

from django.db import connection

from redisutils import mock_redis, reset_redis
from addons import forms, cron
from addons.models import Addon, Category
from tags.models import Tag, AddonTag

import amo
from amo.tests.test_helpers import get_image_path
from services import update


class FormsTest(test_utils.TestCase):
    fixtures = ('base/addon_3615', 'base/addon_3615_categories',
                'addons/blacklisted')

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
        form = forms.AddonFormDetails(request={})
        eq_(form.fields['default_locale'].choices[0][0], 'af')

    def test_slug_blacklist(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': 'submit'}, request=None,
                                    instance=delicious)
        assert not form.is_valid()
        eq_(form.errors['slug'], [u'The slug cannot be: submit.'])

    def test_slug_isdigit(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': '123'}, request=None,
                                    instance=delicious)
        assert not form.is_valid()
        eq_(form.errors['slug'], [u'The slug cannot be: 123.'])


class TestTagsForm(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/platforms', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        category = Category.objects.get(pk=22)
        category.name = 'test'
        category.save()

        self.data = {
            'summary': str(self.addon.summary),
            'name': str(self.addon.name),
            'slug': self.addon.slug,
        }

        self.user = self.addon.authors.all()[0]
        amo.set_user(self.user)

    def add_tags(self, tags):
        data = self.data.copy()
        data.update({'tags': tags})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        assert form.is_valid()
        form.save(self.addon)
        return form

    def get_tag_text(self):
        return [t.tag_text for t in self.addon.tags.no_cache().all()]

    def test_tags(self):
        self.add_tags('foo, bar')
        eq_(self.get_tag_text(), ['bar', 'foo'])

    def test_tags_xss(self):
        self.add_tags('<script>alert("foo")</script>, bar')
        eq_(self.get_tag_text(), ['bar', 'scriptalertfooscript'])

    def test_tags_case_spaces(self):
        self.add_tags('foo, bar')
        self.add_tags('foo,    bar   , Bar, BAR, b a r ')
        eq_(self.get_tag_text(), ['b a r', 'bar', 'foo'])

    def test_tags_spaces(self):
        self.add_tags('foo, bar beer')
        eq_(self.get_tag_text(), ['bar beer', 'foo'])

    def test_tags_unicode(self):
        self.add_tags(u'Österreich')
        eq_(self.get_tag_text(), [u'Österreich'.lower()])

    def add_restricted(self, *args):
        if not args:
            args = ['restartless']
        for arg in args:
            tag = Tag.objects.create(tag_text=arg, restricted=True)
            AddonTag.objects.create(tag=tag, addon=self.addon)

    def test_tags_restricted(self):
        self.add_restricted()
        self.add_tags('foo, bar')
        form = forms.AddonFormBasic(data=self.data, request=None,
                                    instance=self.addon)

        eq_(form.fields['tags'].initial, 'bar, foo')
        eq_(self.get_tag_text(), ['bar', 'foo', 'restartless'])
        self.add_tags('')
        eq_(self.get_tag_text(), ['restartless'])

    def test_tags_error(self):
        self.add_restricted('restartless', 'sdk')
        data = self.data.copy()
        data.update({'tags': 'restartless'})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        eq_(form.errors['tags'][0],
            '"restartless" is a reserved tag and cannot be used.')
        data.update({'tags': 'restartless, sdk'})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        eq_(form.errors['tags'][0],
            '"restartless", "sdk" are reserved tags and cannot be used.')

    @patch('access.acl.action_allowed')
    def test_tags_admin_restricted(self, action_allowed):
        action_allowed.return_value = True
        self.add_restricted('restartless')
        self.add_tags('foo, bar')
        eq_(self.get_tag_text(), ['bar', 'foo'])
        self.add_tags('foo, bar, restartless')
        eq_(self.get_tag_text(), ['bar', 'foo', 'restartless'])
        form = forms.AddonFormBasic(data=self.data, request=None,
                                    instance=self.addon)
        eq_(form.fields['tags'].initial, 'bar, foo, restartless')

    @patch('access.acl.action_allowed')
    def test_tags_admin_restricted_count(self, action_allowed):
        action_allowed.return_value = True
        self.add_restricted()
        self.add_tags('restartless, %s' % (', '.join('tag-test-%s' %
                                                     i for i in range(0, 20))))

    def test_tags_restricted_count(self):
        self.add_restricted()
        self.add_tags(', '.join('tag-test-%s' % i for i in range(0, 20)))

    def test_tags_slugified_count(self):
        self.add_tags(', '.join('tag-test' for i in range(0, 21)))
        eq_(self.get_tag_text(), ['tag-test'])

    def test_tags_limit(self):
        self.add_tags(' %s' % ('t' * 128))

    def test_tags_long(self):
        tag = ' -%s' % ('t' * 128)
        data = self.data.copy()
        data.update({"tags": tag})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        assert not form.is_valid()
        eq_(form.errors['tags'], ['All tags must be 128 characters or less'
                                  ' after invalid characters are removed.'])


class TestIconRemoval(test_utils.TestCase):
    fixtures = ['base/addon_3615']

    # TODO: AddonFormMedia save() method could do with cleaning up
    # so this isn't necessary
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addon = Addon.objects.get(pk=3615)

        class DummyRequest:
            FILES = None
        self.request = DummyRequest()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def get_icon_paths(self):
        path = os.path.join(self.addon.get_icon_dir(), str(self.addon.id))
        return ['%s-%s.png' % (path, size) for size in amo.ADDON_ICON_SIZES]

    @patch('apps.addons.models.Addon.get_icon_dir')
    def testIconUpload(self, get_icon_dir):
        # We no longer use AddonFormMedia to upload icons, so
        # skipping until I can ask andym what the point of this
        # test is.  Additionally, it's called "TestIconRemoval",
        # but it doesn't seem to remove icons.
        return
        get_icon_dir.return_value = self.temp_dir

        for path in self.get_icon_paths():
            assert not os.path.exists(path)

        img = get_image_path('non-animated.png')
        data = {'icon_upload': img, 'icon_type': 'text/png'}
        self.request.FILES = {'icon_upload': open(img)}
        form = forms.AddonFormMedia(data=data, request=self.request,
                                    instance=self.addon)
        assert form.is_valid()
        form.save(self.addon)
        for path in self.get_icon_paths():
            assert os.path.exists(path)


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
            'appVersion': '3.7a1pre',
        }

    def get(self, data):
        up = update.Update(data)
        up.cursor = connection.cursor()
        return up

    def test_beta(self):
        data = self.good_data.copy()
        for good in ['1.0a', '1.0beta2', '1.0 beta2']:
            data['version'] = good
            form = self.get(data)
            assert form.is_valid()
            assert form.is_beta_version

        for bad in ['1.0', 'beta 1.0', '1.0 beta 2']:
            data['version'] = bad
            form = self.get(data)
            assert form.is_valid()
            assert not form.is_beta_version

    def test_app_os(self):
        data = self.good_data.copy()
        data['appOS'] = 'something %s penguin' % amo.PLATFORM_LINUX.api_name
        form = self.get(data)
        assert form.is_valid()
        eq_(form.data['appOS'], amo.PLATFORM_LINUX.id)

    def test_app_version_fails(self):
        data = self.good_data.copy()
        del data['appID']
        form = self.get(data)
        assert not form.is_valid()

    def test_app_version_wrong(self):
        data = self.good_data.copy()
        data['appVersion'] = '67.7'
        form = self.get(data)
        # If you pass through the wrong version that's fine
        # you will just end up with no updates because your
        # version_int will be out.
        assert form.is_valid()

    def test_app_version(self):
        data = self.good_data.copy()
        form = self.get(data)
        assert form.is_valid()
        eq_(form.data['version_int'], 3070000001000)

    def test_sql_injection(self):
        data = self.good_data.copy()
        data['id'] = "'"
        up = self.get(data)
        assert not up.is_valid()

    def test_inactive(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(disabled_by_user=True)

        up = self.get(self.good_data)
        assert not up.is_valid()


class TestCategoryForm(test_utils.TestCase):
    fixtures = ['base/apps']

    def test_no_possible_categories(self):
        Category.objects.create(type=amo.ADDON_SEARCH,
                                application_id=amo.FIREFOX.id)
        addon = Addon.objects.create(type=amo.ADDON_SEARCH)
        form = forms.CategoryFormSet(addon=addon)
        apps = [f.app for f in form.forms]
        eq_(apps, [amo.FIREFOX])
