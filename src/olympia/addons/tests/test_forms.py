# -*- coding: utf-8 -*-
import os
import tempfile
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.test.client import RequestFactory

from mock import patch

from olympia import amo, core
from olympia.addons import forms
from olympia.addons.models import Addon, Category
from olympia.amo.tests import TestCase, addon_factory, req_factory_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import rm_local_tmp_dir
from olympia.tags.models import AddonTag, Tag
from olympia.users.models import UserProfile


class TestAddonFormSupport(TestCase):

    def test_bogus_support_url(self):
        form = forms.AddonFormSupport(
            {'support_url': 'javascript://something.com'}, request=None)
        assert not form.is_valid()
        assert form.errors['support_url'] == [u'Enter a valid URL.']

    def test_ftp_support_url(self):
        form = forms.AddonFormSupport(
            {'support_url': 'ftp://foo.com'}, request=None)
        assert not form.is_valid()
        assert form.errors['support_url'] == [u'Enter a valid URL.']

    def test_http_support_url(self):
        form = forms.AddonFormSupport(
            {'support_url': 'http://foo.com'}, request=None)
        assert form.is_valid()


class FormsTest(TestCase):
    fixtures = ('base/addon_3615', 'base/addon_3615_categories',
                'addons/denied')

    def setUp(self):
        super(FormsTest, self).setUp()
        self.existing_name = 'Delicious Bookmarks'
        self.non_existing_name = 'Does Not Exist'
        self.error_msg = 'This name is already in use. Please choose another.'
        self.request = req_factory_factory('/')

    def test_locales(self):
        form = forms.AddonFormDetails(request=self.request)
        assert form.fields['default_locale'].choices[0][0] == 'af'

    def test_slug_deny(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': 'submit'}, request=self.request,
                                    instance=delicious)
        assert not form.is_valid()
        assert form.errors['slug'] == (
            [u'The slug cannot be "submit". Please choose another.'])

    def test_name_trademark_mozilla(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic(
            {'name': 'Delicious Mozilla', 'summary': 'foo', 'slug': 'bar'},
            request=self.request,
            instance=delicious)

        assert not form.is_valid()
        assert form.errors['name'].data[0].message.startswith(
            u'Add-on names cannot contain the Mozilla or Firefox trademarks.')

    def test_name_trademark_firefox(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic(
            {'name': 'Delicious Firefox', 'summary': 'foo', 'slug': 'bar'},
            request=self.request,
            instance=delicious)
        assert not form.is_valid()
        assert form.errors['name'].data[0].message.startswith(
            u'Add-on names cannot contain the Mozilla or Firefox trademarks.')

    def test_name_trademark_allowed_for_prefix(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic(
            {'name': 'Delicious for Mozilla', 'summary': 'foo', 'slug': 'bar'},
            request=self.request,
            instance=delicious)

        assert form.is_valid()

    def test_name_no_trademark(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic(
            {'name': 'Delicious Dumdidum', 'summary': 'foo', 'slug': 'bar'},
            request=self.request,
            instance=delicious)

        assert form.is_valid()

    def test_bogus_homepage(self):
        form = forms.AddonFormDetails(
            {'homepage': 'javascript://something.com'}, request=self.request)
        assert not form.is_valid()
        assert form.errors['homepage'] == [u'Enter a valid URL.']

    def test_ftp_homepage(self):
        form = forms.AddonFormDetails(
            {'homepage': 'ftp://foo.com'}, request=self.request)
        assert not form.is_valid()
        assert form.errors['homepage'] == [u'Enter a valid URL.']

    def test_homepage_is_not_required(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormDetails(
            {'default_locale': 'en-US'},
            request=self.request, instance=delicious)
        assert form.is_valid()

    def test_slug_isdigit(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': '123'}, request=self.request,
                                    instance=delicious)
        assert not form.is_valid()
        assert form.errors['slug'] == (
            [u'The slug cannot be "123". Please choose another.'])


class TestTagsForm(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestTagsForm, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        category = Category.objects.get(pk=22)
        category.db_name = 'test'
        category.save()

        self.data = {
            'summary': str(self.addon.summary),
            'name': str(self.addon.name),
            'slug': self.addon.slug,
        }

        self.user = self.addon.authors.all()[0]
        core.set_user(self.user)
        self.request = req_factory_factory('/')

    def add_tags(self, tags):
        data = self.data.copy()
        data.update({'tags': tags})
        form = forms.AddonFormBasic(data=data, request=self.request,
                                    instance=self.addon)
        assert form.is_valid()
        form.save(self.addon)
        return form

    def get_tag_text(self):
        return [t.tag_text for t in self.addon.tags.all()]

    def test_tags(self):
        self.add_tags('foo, bar')
        assert self.get_tag_text() == ['bar', 'foo']

    def test_tags_xss(self):
        self.add_tags('<script>alert("foo")</script>, bar')
        assert self.get_tag_text() == ['bar', 'scriptalertfooscript']

    def test_tags_case_spaces(self):
        self.add_tags('foo, bar')
        self.add_tags('foo,    bar   , Bar, BAR, b a r ')
        assert self.get_tag_text() == ['b a r', 'bar', 'foo']

    def test_tags_spaces(self):
        self.add_tags('foo, bar beer')
        assert self.get_tag_text() == ['bar beer', 'foo']

    def test_tags_unicode(self):
        self.add_tags(u'Österreich')
        assert self.get_tag_text() == [u'Österreich'.lower()]

    def add_restricted(self, *args):
        if not args:
            args = ['i_am_a_restricted_tag']
        for arg in args:
            tag = Tag.objects.create(tag_text=arg, restricted=True)
            AddonTag.objects.create(tag=tag, addon=self.addon)

    def test_tags_restricted(self):
        self.add_restricted()
        self.add_tags('foo, bar')
        form = forms.AddonFormBasic(data=self.data, request=self.request,
                                    instance=self.addon)

        assert form.fields['tags'].initial == 'bar, foo'
        assert self.get_tag_text() == ['bar', 'foo', 'i_am_a_restricted_tag']
        self.add_tags('')
        assert self.get_tag_text() == ['i_am_a_restricted_tag']

    def test_tags_error(self):
        self.add_restricted('i_am_a_restricted_tag', 'sdk')
        data = self.data.copy()
        data.update({'tags': 'i_am_a_restricted_tag'})
        form = forms.AddonFormBasic(data=data, request=self.request,
                                    instance=self.addon)
        assert form.errors['tags'][0] == (
            '"i_am_a_restricted_tag" is a reserved tag and cannot be used.')
        data.update({'tags': 'i_am_a_restricted_tag, sdk'})
        form = forms.AddonFormBasic(data=data, request=self.request,
                                    instance=self.addon)
        assert form.errors['tags'][0] == (
            '"i_am_a_restricted_tag", "sdk" are reserved tags and'
            ' cannot be used.')

    @patch('olympia.access.acl.action_allowed')
    def test_tags_admin_restricted(self, action_allowed):
        action_allowed.return_value = True
        self.add_restricted('i_am_a_restricted_tag')
        self.add_tags('foo, bar')
        assert self.get_tag_text() == ['bar', 'foo']
        self.add_tags('foo, bar, i_am_a_restricted_tag')

        assert self.get_tag_text() == ['bar', 'foo', 'i_am_a_restricted_tag']
        form = forms.AddonFormBasic(data=self.data, request=self.request,
                                    instance=self.addon)
        assert form.fields['tags'].initial == 'bar, foo, i_am_a_restricted_tag'

    @patch('olympia.access.acl.action_allowed')
    def test_tags_admin_restricted_count(self, action_allowed):
        action_allowed.return_value = True
        self.add_restricted()
        self.add_tags('i_am_a_restricted_tag, %s' % (', '.join('tag-test-%s' %
                                                     i for i in range(0, 20))))

    def test_tags_restricted_count(self):
        self.add_restricted()
        self.add_tags(', '.join('tag-test-%s' % i for i in range(0, 20)))

    def test_tags_slugified_count(self):
        self.add_tags(', '.join('tag-test' for i in range(0, 21)))
        assert self.get_tag_text() == ['tag-test']

    def test_tags_limit(self):
        self.add_tags(' %s' % ('t' * 128))

    def test_tags_long(self):
        tag = ' -%s' % ('t' * 128)
        data = self.data.copy()
        data.update({"tags": tag})
        form = forms.AddonFormBasic(data=data, request=self.request,
                                    instance=self.addon)
        assert not form.is_valid()
        assert form.errors['tags'] == [
            'All tags must be 128 characters or less after invalid characters'
            ' are removed.']


class TestIconForm(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestIconForm, self).setUp()
        self.temp_dir = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.addon = Addon.objects.get(pk=3615)

        class DummyRequest:
            FILES = None
        self.request = DummyRequest()
        self.icon_path = os.path.join(settings.TMP_PATH, 'icon')
        if not os.path.exists(self.icon_path):
            os.makedirs(self.icon_path)

    def tearDown(self):
        rm_local_tmp_dir(self.temp_dir)
        super(TestIconForm, self).tearDown()

    def get_icon_paths(self):
        path = os.path.join(self.addon.get_icon_dir(), str(self.addon.id))
        return ['%s-%s.png' % (path, size) for size in amo.ADDON_ICON_SIZES]

    @patch('olympia.amo.models.ModelBase.update')
    def test_icon_modified(self, update_mock):
        name = 'transparent.png'
        form = forms.AddonFormMedia({'icon_upload_hash': name},
                                    request=self.request,
                                    instance=self.addon)

        dest = os.path.join(self.icon_path, name)
        with storage.open(dest, 'w') as f:
            shutil.copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon=self.addon)
        assert update_mock.called


class TestCategoryForm(TestCase):

    def test_no_possible_categories(self):
        Category.objects.create(type=amo.ADDON_SEARCH,
                                application=amo.FIREFOX.id)
        addon = addon_factory(type=amo.ADDON_SEARCH)
        request = req_factory_factory('/')
        form = forms.CategoryFormSet(addon=addon, request=request)
        apps = [f.app for f in form.forms]
        assert apps == [amo.FIREFOX]


class TestThemeForm(TestCase):

    # Don't save image, we use a fake one.
    @patch('olympia.addons.forms.save_theme')
    def test_long_author_or_display_username(self, mock_save_theme):
        # Bug 1181751.
        user = UserProfile.objects.create(email='foo@bar.com',
                                          username='a' * 255,
                                          display_name='b' * 255)
        request = RequestFactory()
        request.user = user
        cat = Category.objects.create(type=amo.ADDON_PERSONA)
        form = forms.ThemeForm({
            'name': 'my theme',
            'slug': 'my-theme',
            'category': cat.pk,
            'header': 'some_file.png',
            'agreed': True,
            'header_hash': 'hash',
            'license': 1}, request=request)
        assert form.is_valid()
        # Make sure there's no database issue, like too long data for the
        # author or display_username fields.
        form.save()
