# -*- coding: utf-8 -*-
import os
import tempfile

from mock import patch
from nose.tools import eq_

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.test.client import RequestFactory

import amo
import amo.tests
from amo.tests import addon_factory
from amo.tests.test_helpers import get_image_path
from amo.utils import rm_local_tmp_dir
from addons import forms
from addons.models import Addon, Category
from files.helpers import copyfileobj
from tags.models import Tag, AddonTag
from users.models import UserProfile


class FormsTest(amo.tests.TestCase):
    fixtures = ('base/addon_3615', 'base/addon_3615_categories',
                'addons/blacklisted')

    def setUp(self):
        super(FormsTest, self).setUp()
        self.existing_name = 'Delicious Bookmarks'
        self.non_existing_name = 'Does Not Exist'
        self.error_msg = 'This name is already in use. Please choose another.'

    def test_update_addon_non_existing_name(self):
        """An add-on edit can change the name to any non-existing name."""
        addon = addon_factory(name='some name')
        form = forms.AddonForm(dict(name=self.non_existing_name),
                               instance=addon)
        form.is_valid()
        assert 'name' not in form.errors

    def test_update_addon_existing_name(self):
        """An add-on edit can't change the name to an existing add-on name."""
        addon = addon_factory(name='some name')
        form = forms.AddonForm(dict(name=self.existing_name), instance=addon)
        assert not form.is_valid()
        assert form.errors['name'][0] == self.error_msg

    def test_update_addon_existing_name_used_by_unlisted(self):
        """An add-on edit can change the name to an existing name used by an
        unlisted add-on."""
        Addon.objects.get(pk=3615).update(is_listed=False)
        addon = addon_factory(name='some name')
        form = forms.AddonForm(dict(name=self.existing_name), instance=addon)
        form.is_valid()
        assert 'name' not in form.errors

    def test_update_addon_existing_name_used_by_listed(self):
        """An unlisted add-on edit can change the name to an existing name used
        by an listed add-on."""
        addon = addon_factory(name='some name', is_listed=False)
        form = forms.AddonForm(dict(name=self.existing_name), instance=addon)
        form.is_valid()
        assert 'name' not in form.errors

    def test_update_addon_existing_name_used_by_other_type(self):
        """An add-on edit can change the name to an existing name used by
        another add-on type."""
        addon = addon_factory(name='some name', type=amo.ADDON_PERSONA)
        form = forms.AddonForm(dict(name=self.existing_name), instance=addon)
        form.is_valid()
        assert 'name' not in form.errors

    def test_old(self):
        """
        Exiting add-ons shouldn't be able to use someone else's name.
        """
        a = Addon.objects.create(type=1)
        f = forms.AddonFormBasic(dict(name=self.existing_name), request=None,
                                 instance=a)
        assert not f.is_valid()
        assert f.errors.get('name')[0][1] == self.error_msg

    def test_old_same(self):
        """
        Exiting add-ons should be able to re-use their name.
        """
        delicious = Addon.objects.get()
        f = forms.AddonFormBasic(dict(name=self.existing_name), request=None,
                                 instance=delicious)
        f.is_valid()
        assert f.errors.get('name') is None

    def test_locales(self):
        form = forms.AddonFormDetails(request={})
        assert form.fields['default_locale'].choices[0][0] == 'af'

    def test_slug_blacklist(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': 'submit'}, request=None,
                                    instance=delicious)
        assert not form.is_valid()
        assert form.errors['slug'] == [u'The slug cannot be "submit". Please choose another.']

    def test_slug_isdigit(self):
        delicious = Addon.objects.get()
        form = forms.AddonFormBasic({'slug': '123'}, request=None,
                                    instance=delicious)
        assert not form.is_valid()
        assert form.errors['slug'] == [u'The slug cannot be "123". Please choose another.']


class TestTagsForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestTagsForm, self).setUp()
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
            args = ['restartless']
        for arg in args:
            tag = Tag.objects.create(tag_text=arg, restricted=True)
            AddonTag.objects.create(tag=tag, addon=self.addon)

    def test_tags_restricted(self):
        self.add_restricted()
        self.add_tags('foo, bar')
        form = forms.AddonFormBasic(data=self.data, request=None,
                                    instance=self.addon)
        assert form.fields['tags'].initial == 'bar, foo'
        assert self.get_tag_text() == ['bar', 'foo', 'restartless']
        self.add_tags('')
        assert self.get_tag_text() == ['restartless']

    def test_tags_error(self):
        self.add_restricted('restartless', 'sdk')
        data = self.data.copy()
        data.update({'tags': 'restartless'})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        assert form.errors['tags'][0] == '"restartless" is a reserved tag and cannot be used.'
        data.update({'tags': 'restartless, sdk'})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        assert form.errors['tags'][0] == '"restartless", "sdk" are reserved tags and cannot be used.'

    @patch('access.acl.action_allowed')
    def test_tags_admin_restricted(self, action_allowed):
        action_allowed.return_value = True
        self.add_restricted('restartless')
        self.add_tags('foo, bar')
        assert self.get_tag_text() == ['bar', 'foo']
        self.add_tags('foo, bar, restartless')
        assert self.get_tag_text() == ['bar', 'foo', 'restartless']
        form = forms.AddonFormBasic(data=self.data, request=None,
                                    instance=self.addon)
        assert form.fields['tags'].initial == 'bar, foo, restartless'

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
        assert self.get_tag_text() == ['tag-test']

    def test_tags_limit(self):
        self.add_tags(' %s' % ('t' * 128))

    def test_tags_long(self):
        tag = ' -%s' % ('t' * 128)
        data = self.data.copy()
        data.update({"tags": tag})
        form = forms.AddonFormBasic(data=data, request=None,
                                    instance=self.addon)
        assert not form.is_valid()
        assert form.errors['tags'] == ['All tags must be 128 characters or less' ' after invalid characters are removed.']


class TestIconForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    # TODO: AddonFormMedia save() method could do with cleaning up
    # so this isn't necessary
    def setUp(self):
        super(TestIconForm, self).setUp()
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
        super(TestIconForm, self).tearDown()

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
        with storage.open(dest, 'w') as f:
            copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon=self.addon)
        assert update_mock.called


class TestCategoryForm(amo.tests.TestCase):

    def test_no_possible_categories(self):
        Category.objects.create(type=amo.ADDON_SEARCH,
                                application=amo.FIREFOX.id)
        addon = Addon.objects.create(type=amo.ADDON_SEARCH)
        form = forms.CategoryFormSet(addon=addon)
        apps = [f.app for f in form.forms]
        assert apps == [amo.FIREFOX]


class TestThemeForm(amo.tests.TestCase):

    @patch('addons.forms.save_theme')  # Don't save image, we use a fake one.
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
        # author or display_sername fields.
        form.save()
