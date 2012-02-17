# -*- coding: utf-8 -*-
import os
import shutil
import tempfile

from mock import patch
from nose.tools import eq_

from django.conf import settings

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from amo.utils import rm_local_tmp_dir
from addons import forms, cron
from addons.models import Addon, AddonDeviceType, Category, DeviceType, Webapp
from tags.models import Tag, AddonTag
from addons.forms import DeviceTypeForm


class FormsTest(amo.tests.TestCase):
    fixtures = ('base/addon_3615', 'base/addon_3615_categories',
                'addons/blacklisted')

    def setUp(self):
        super(FormsTest, self).setUp()
        cron.build_reverse_name_lookup()
        self.existing_name = 'Delicious Bookmarks'
        self.error_msg = 'This name is already in use. Please choose another.'

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


class TestTagsForm(amo.tests.TestCase):
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


class TestIconForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    # TODO: AddonFormMedia save() method could do with cleaning up
    # so this isn't necessary
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addon = Addon.objects.get(pk=3615)

        class DummyRequest:
            FILES = None
        self.request = DummyRequest()
        self.icon_path = os.path.join(settings.TMP_PATH, 'icon')
        if not os.path.exists(self.icon_path):
            os.makedirs(self.icon_path)

    def tearDown(self):
        rm_local_tmp_dir(self.temp_dir)

    def get_icon_paths(self):
        path = os.path.join(self.addon.get_icon_dir(), str(self.addon.id))
        return ['%s-%s.png' % (path, size) for size in amo.ADDON_ICON_SIZES]

    @patch('apps.addons.models.Addon.get_icon_dir')
    def testIconUpload(self, get_icon_dir):
        # TODO(gkoberger): clarify this please.
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

    @patch('amo.models.ModelBase.update')
    def test_icon_modified(self, update_mock):
        name = 'transparent.png'
        form = forms.AddonFormMedia({'icon_upload_hash': name},
                                    request=self.request,
                                    instance=self.addon)

        dest = os.path.join(self.icon_path, name)
        shutil.copyfile(get_image_path(name), dest)

        assert form.is_valid()
        form.save(addon=self.addon)
        assert update_mock.called


class TestCategoryForm(amo.tests.TestCase):
    fixtures = ['base/apps']

    def test_no_possible_categories(self):
        Category.objects.create(type=amo.ADDON_SEARCH,
                                application_id=amo.FIREFOX.id)
        addon = Addon.objects.create(type=amo.ADDON_SEARCH)
        form = forms.CategoryFormSet(addon=addon)
        apps = [f.app for f in form.forms]
        eq_(apps, [amo.FIREFOX])


class TestDeviceTypeForm(amo.tests.TestCase):
    fixtures = ['base/337141-steamcube']

    def test_device_types(self):
        dtype = DeviceType.objects.create(name='fligphone', class_name='phone')
        webapp = Webapp.objects.get(id=337141)
        addondt = AddonDeviceType.objects.create(addon=webapp,
                                                 device_type=dtype)
        types = DeviceType.objects.values_list('id', flat=True)
        form = DeviceTypeForm(addon=webapp)
        eq_(webapp.device_types, [addondt.device_type])
        eq_(list(form.initial['device_types']), list(types))
