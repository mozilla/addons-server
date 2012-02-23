import json
import os
import re
import tempfile

from django.conf import settings
from django.core.cache import cache

import mock
from nose import SkipTest
from nose.tools import eq_
from PIL import Image
from pyquery import PyQuery as pq
from waffle.models import Switch

import amo
import amo.tests
from amo.tests import assert_required, formset, initial
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.forms import AddonFormBasic
from addons.models import (Addon, AddonCategory,
                           AddonDeviceType, AddonUser, Category, DeviceType)
from bandwagon.models import Collection, CollectionAddon, FeaturedCollection
from mkt.developers.models import ActivityLog
from users.models import UserProfile


def get_section_url(addon, section, edit=False):
    args = [addon.slug, section]
    if edit:
        args.append('edit')
    return reverse('mkt.developers.addons.section', args=args)


class TestEdit(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5579', 'base/addon_3615_categories']

    def setUp(self):
        super(TestEdit, self).setUp()
        addon = self.get_addon()
        assert self.client.login(username='del@icio.us', password='password')

        a = AddonCategory.objects.filter(addon=addon, category__id=22)[0]
        a.feature = False
        a.save()
        AddonCategory.objects.filter(addon=addon,
            category__id__in=[23, 24]).delete()
        cache.clear()

        self.url = addon.get_dev_url()
        self.user = UserProfile.objects.get(pk=55021)

        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_url(self, section, edit=False):
        return get_section_url(self.addon, section, edit)

    def get_dict(self, **kw):
        fs = formset(self.cat_initial, initial_count=1)
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary'}
        result.update(**kw)
        result.update(fs)
        return result


class TestEditListingWebapp(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = Addon.objects.get(id=337141)
        self.url = self.webapp.get_dev_url()

    @mock.patch.object(settings, 'APP_PREVIEW', False)
    def test_apps_context(self):
        r = self.client.get(self.url)
        eq_(r.context['webapp'], True)
        eq_(pq(r.content)('title').text(),
            'Edit Listing | %s | Mozilla Marketplace' % self.webapp.name)

    def test_nav_links(self):
        r = self.client.get(self.url)
        doc = pq(r.content)('#edit-addon-nav')
        eq_(doc.length, 1)
        eq_(doc('.view-stats').length, 0)


class TestEditBasicWebapp(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        Switch.objects.create(name='marketplace', active=True)
        self.webapp = self.get_webapp()
        self.cat = Category.objects.create(name='Games', type=amo.ADDON_WEBAPP)
        self.dtype = DeviceType.objects.create(name='fligphone',
                                               class_name='phone')
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=self.dtype)
        self.url = get_section_url(self.webapp, 'basic')
        self.edit_url = get_section_url(self.webapp, 'basic', edit=True)
        ctx = self.client.get(self.edit_url).context
        self.cat_initial = initial(ctx['cat_form'].initial_forms[0])
        del self.cat_initial['application']

    def get_webapp(self):
        return Addon.objects.get(id=337141)

    def get_dict(self, **kw):
        fs = formset(self.cat_initial, initial_count=1)
        result = {'device_types': self.dtype, 'name': 'new name',
                  'slug': 'test_slug', 'summary': 'new summary'}
        result.update(**kw)
        result.update(fs)
        return result

    def test_apps_context(self):
        r = self.client.get(self.url)
        eq_(r.context['webapp'], True)

    def test_appslug_visible(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#slug_edit').remove('a, em').text(),
            u'/\u2026/%s' % self.webapp.app_slug)

    def test_edit_name_required(self):
        r = self.client.post(self.edit_url, self.get_dict(name=''))
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_max_length(self):
        r = self.client.post(self.edit_url, self.get_dict(name='x' * 129))
        self.assertFormError(r, 'form', 'name',
                             'Ensure this value has at most 128 characters '
                             '(it has 129).')

    def test_edit_slug_success(self):
        webapp = self.webapp
        data = self.get_dict()
        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)
        eq_(self.get_webapp().app_slug, data['slug'])
        # Make sure only the app_slug changed.
        eq_(self.get_webapp().slug, webapp.slug)

    def test_edit_slug_dupe(self):
        webapp = self.webapp
        Addon.objects.create(type=amo.ADDON_WEBAPP, app_slug='dupe')
        data = self.get_dict(slug='dupe')
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'form', 'slug',
                             'This slug is already in use.')
        # Nothing changed.
        eq_(self.get_webapp().slug, webapp.slug)
        eq_(self.get_webapp().app_slug, webapp.app_slug)

    def test_categories_listed(self):
        r = self.client.post(self.url)
        ul = pq(r.content)('#addon-categories-edit ul')
        li = ul.find('li')
        eq_(li.length, 1)
        eq_(li.text(), unicode(self.cat.name))

    def test_edit_categories_add(self):
        new = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        self.cat_initial['categories'] = [self.cat.id, new.id]
        self.client.post(self.edit_url, self.get_dict())
        app_cats = self.get_webapp().categories.values_list('id', flat=True)
        eq_(sorted(app_cats), self.cat_initial['categories'])

    def test_edit_categories_addandremove(self):
        new = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        self.cat_initial['categories'] = [new.id]
        self.client.post(self.edit_url, self.get_dict())
        app_cats = self.get_webapp().categories.values_list('id', flat=True)
        eq_(sorted(app_cats), self.cat_initial['categories'])

    def test_edit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.edit_url, formset(self.cat_initial,
                                                    initial_count=1))
        assert_required(r.context['cat_form'].errors[0]['categories'][0])

    def test_edit_categories_max(self):
        new1 = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        new2 = Category.objects.create(name='Lifestyle', type=amo.ADDON_WEBAPP)
        self.cat_initial['categories'] = [self.cat.id, new1.id, new2.id]
        r = self.client.post(self.edit_url, formset(self.cat_initial,
                                                    initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['You can have only 2 categories.'])

    def test_devices_listed(self):
        r = self.client.post(self.url, self.get_dict())
        eq_(pq(r.content)('#addon-device-types-edit').text(), self.dtype.name)

    def test_edit_devices_add(self):
        new = DeviceType.objects.create(name='iSlate', class_name='slate')
        data = self.get_dict()
        data['device_types'] = [self.dtype.id, new.id]
        self.client.post(self.edit_url, data)
        devicetypes = self.get_webapp().device_types
        eq_([d.id for d in devicetypes], list(data['device_types']))

    def test_edit_devices_addandremove(self):
        new = DeviceType.objects.create(name='iSlate', class_name='slate')
        data = self.get_dict()
        data['device_types'] = [new.id]
        self.client.post(self.edit_url, data)
        devicetypes = self.get_webapp().device_types
        eq_([d.id for d in devicetypes], list(data['device_types']))

    def test_edit_devices_add_required(self):
        data = self.get_dict()
        data['device_types'] = []
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'device_type_form', 'device_types',
                             'This field is required.')


class TestEditBasic(TestEdit):

    def setUp(self):
        super(TestEditBasic, self).setUp()
        self.basic_edit_url = self.get_url('basic', edit=True)
        ctx = self.client.get(self.basic_edit_url).context
        self.cat_initial = initial(ctx['cat_form'].initial_forms[0])

    def test_redirect(self):
        # /addon/:id => /addon/:id/edit
        r = self.client.get('/en-US/developers/addon/3615/', follow=True)
        self.assertRedirects(r, self.url, 301)

    def test_addons_context(self):
        for url in (self.url, self.basic_edit_url):
            eq_(self.client.get(url).context['webapp'], False)

    def test_edit(self):
        old_name = self.addon.name
        data = self.get_dict()

        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(unicode(addon.name), data['name'])
        eq_(addon.name.id, old_name.id)

        eq_(unicode(addon.slug), data['slug'])
        eq_(unicode(addon.summary), data['summary'])

    def test_edit_check_description(self):
        # Make sure bug 629779 doesn't return.
        old_desc = self.addon.description
        data = self.get_dict()

        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(addon.description, old_desc)

    def test_edit_slug_invalid(self):
        old_edit = self.basic_edit_url
        data = self.get_dict(name='', slug='invalid')
        r = self.client.post(self.basic_edit_url, data)
        doc = pq(r.content)
        eq_(doc('form').attr('action'), old_edit)

    def test_edit_slug_valid(self):
        old_edit = self.basic_edit_url
        data = self.get_dict(slug='valid')
        r = self.client.post(self.basic_edit_url, data)
        doc = pq(r.content)
        assert doc('form').attr('action') != old_edit

    def test_edit_summary_escaping(self):
        data = self.get_dict()
        data['summary'] = '<b>oh my</b>'
        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)

        # Fetch the page so the LinkifiedTranslation gets in cache.
        r = self.client.get(reverse('mkt.developers.addons.edit',
                                    args=[data['slug']]))
        eq_(pq(r.content)('[data-name=summary]').html().strip(),
            '<span lang="en-us">&lt;b&gt;oh my&lt;/b&gt;</span>')

        # Now make sure we don't have escaped content in the rendered form.
        form = AddonFormBasic(instance=self.get_addon(), request=object())
        eq_(pq('<body>%s</body>' % form['summary'])('[lang="en-us"]').html(),
            '<b>oh my</b>')

    def test_edit_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        # Make sure we get errors when they are just regular users.
        eq_(r.status_code, 403)

        devuser = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.get_addon(), user=devuser,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = self.client.post(self.basic_edit_url, data)

        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(unicode(addon.name), data['name'])

        eq_(unicode(addon.slug), data['slug'])
        eq_(unicode(addon.summary), data['summary'])

    def test_edit_name_required(self):
        data = self.get_dict(name='', slug='test_addon')
        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_spaces(self):
        data = self.get_dict(name='    ', slug='test_addon')
        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', 'This slug is already in use.')

    def test_edit_categories_add(self):
        eq_([c.id for c in self.get_addon().all_categories], [22])
        self.cat_initial['categories'] = [22, 23]

        self.client.post(self.basic_edit_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 23])

    def _feature_addon(self, addon_id=3615):
        c = CollectionAddon.objects.create(addon_id=addon_id,
            collection=Collection.objects.create())
        FeaturedCollection.objects.create(collection=c.collection,
                                          application_id=amo.FIREFOX.id)

    def test_edit_categories_add_creatured(self):
        raise SkipTest()
        """Ensure that categories cannot be changed for creatured add-ons."""
        self._feature_addon()

        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)

        eq_(r.context['cat_form'].errors[0]['categories'],
            ['Categories cannot be changed while your add-on is featured for '
             'this application.'])
        # This add-on's categories should not change.
        eq_(sorted(addon_cats), [22])

    def test_edit_categories_add_new_creatured_admin(self):
        """Ensure that admins can change categories for creatured add-ons."""
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self._feature_addon()
        from addons.cron import reset_featured_addons
        reset_featured_addons()
        r = self.client.get(self.basic_edit_url)
        doc = pq(r.content)
        eq_(doc('#addon-categories-edit div.addon-app-cats').length, 1)
        eq_(doc('#addon-categories-edit > p').length, 0)
        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_('categories' in r.context['cat_form'].errors[0], False)
        # This add-on's categories should change.
        eq_(sorted(addon_cats), [22, 23])

    def test_edit_categories_disable_creatured(self):
        """Ensure that other forms are okay when disabling category changes."""
        self._feature_addon()
        self.cat_initial['categories'] = [22, 23]
        data = self.get_dict()
        self.client.post(self.basic_edit_url, data)
        eq_(unicode(self.get_addon().name), data['name'])

    def test_edit_categories_no_disclaimer(self):
        """Ensure that there is a not disclaimer for non-creatured add-ons."""
        r = self.client.get(self.basic_edit_url)
        doc = pq(r.content)
        eq_(doc('#addon-categories-edit div.addon-app-cats').length, 1)
        eq_(doc('#addon-categories-edit > p').length, 0)

    def test_edit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=23).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22, 24]
        self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 24])

    def test_edit_categories_xss(self):
        c = Category.objects.get(id=22)
        c.name = '<script>alert("test");</script>'
        c.save()

        self.cat_initial['categories'] = [22, 24]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))

        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content

    def test_edit_categories_remove(self):
        c = Category.objects.get(id=23)
        AddonCategory(addon=self.addon, category=c).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22]
        self.client.post(self.basic_edit_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22])

    def test_edit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['This field is required.'])

    def test_edit_categories_max(self):
        eq_(amo.MAX_CATEGORIES, 2)
        self.cat_initial['categories'] = [22, 23, 24]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['You can have only 2 categories.'])

    def test_edit_categories_other_failure(self):
        Category.objects.get(id=22).update(misc=True)
        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['The miscellaneous category cannot be combined with additional '
             'categories.'])

    def test_edit_categories_nonexistent(self):
        self.cat_initial['categories'] = [100]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['Select a valid choice. 100 is not one of the available '
             'choices.'])

    def test_edit_name_not_empty(self):
        data = self.get_dict(name='', slug=self.addon.slug,
                             summary=self.addon.summary)
        r = self.client.post(self.basic_edit_url, data)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_max_length(self):
        data = self.get_dict(name='xx' * 70, slug=self.addon.slug,
                             summary=self.addon.summary)
        r = self.client.post(self.basic_edit_url, data)
        self.assertFormError(r, 'form', 'name',
                             'Ensure this value has at most 50 '
                             'characters (it has 140).')

    def test_edit_summary_max_length(self):
        data = self.get_dict(name=self.addon.name, slug=self.addon.slug,
                             summary='x' * 251)
        r = self.client.post(self.basic_edit_url, data)
        self.assertFormError(r, 'form', 'summary',
                             'Ensure this value has at most 250 '
                             'characters (it has 251).')

    def get_l10n_urls(self):
        paths = ('mkt.developers.addons.edit', 'mkt.developers.addons.profile')
        return [reverse(p, args=['a3615']) for p in paths]

    def test_l10n(self):
        Addon.objects.get(id=3615).update(default_locale='en-US')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'en-us',
                'l10n menu not visible for %s' % url)

    def test_l10n_not_us(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr',
                'l10n menu not visible for %s' % url)

    def test_l10n_not_us_id_url(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            url = '/id' + url[6:]
            r = self.client.get(url, follow=True)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr',
                'l10n menu not visible for %s' % url)


class TestEditMedia(TestEdit):

    def setUp(self):
        super(TestEditMedia, self).setUp()
        self.media_edit_url = self.get_url('media', True)
        self.icon_upload = reverse('mkt.developers.addons.upload_icon',
                                   args=[self.addon.slug])
        self.preview_upload = reverse('mkt.developers.addons.upload_preview',
                                      args=[self.addon.slug])
        self.old_settings = {'preview': settings.PREVIEW_THUMBNAIL_PATH,
                             'icons': settings.ADDON_ICONS_PATH}
        settings.PREVIEW_THUMBNAIL_PATH = tempfile.mkstemp()[1] + '%s/%d.png'
        settings.ADDON_ICONS_PATH = tempfile.mkdtemp()

    def tearDown(self):
        super(TestEditMedia, self).tearDown()
        settings.PREVIEW_THUMBNAIL_PATH = self.old_settings['preview']
        settings.ADDON_ICONS_PATH = self.old_settings['icons']

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.media_edit_url).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form()], **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def test_edit_media_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/appearance-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_uploadedicon(self):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        url = addon.get_icon_url(64)
        assert ('addon_icon/%s' % addon.id) in url, (
            'Unexpected path: %r' % url)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (32, 12))

    def test_edit_media_icon_log(self):
        self.test_edit_media_uploadedicon()
        log = ActivityLog.objects.all()
        eq_(log.count(), 1)
        eq_(log[0].action, amo.LOG.CHANGE_ICON.id)

    def test_edit_media_uploadedicon_noresize(self):
        img = "%s/img/notifications/error.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        addon_url = addon.get_icon_url(64).split('?')[0]
        assert addon_url.endswith('images/addon_icon/%s-64.png' % addon.id), (
            'Unexpected path: %r' % addon_url)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (48, 48))

    def test_edit_media_uploadedicon_wrongtype(self):
        img = '%s/js/zamboni/devhub.js' % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons must be either PNG or JPG.')

    def setup_image_status(self):
        addon = self.get_addon()
        self.icon_dest = os.path.join(addon.get_icon_dir(),
                                      '%s-32.png' % addon.id)
        os.makedirs(os.path.dirname(self.icon_dest))
        open(self.icon_dest, 'w')

        self.preview = addon.previews.create()
        self.preview.save()
        os.makedirs(os.path.dirname(self.preview.thumbnail_path))
        open(self.preview.thumbnail_path, 'w')

        self.url = reverse('mkt.developers.ajax.image.status',
                           args=[addon.slug])

    def test_image_status_no_choice(self):
        addon = self.get_addon()
        addon.update(icon_type='')
        url = reverse('mkt.developers.ajax.image.status', args=[addon.slug])
        result = json.loads(self.client.get(url).content)
        assert result['icons']

    def test_image_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_fails(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        result = json.loads(self.client.get(self.url).content)
        assert not result['icons']

    def test_preview_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

        # No previews means that all the images are done.
        self.addon.previews.all().delete()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

    def test_preview_status_fails(self):
        self.setup_image_status()
        os.remove(self.preview.thumbnail_path)
        result = json.loads(self.client.get(self.url).content)
        assert not result['previews']

    def test_image_status_persona(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        self.get_addon().update(type=amo.ADDON_PERSONA)
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_default(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        self.get_addon().update(icon_type='icon/photos')
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_icon_animated(self):
        filehandle = open(get_image_path('animated.png'), 'rb')
        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons cannot be animated.')

    def preview_add(self, amount=1):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)
        data_formset = self.formset_media(**data)
        url = self.preview_upload

        r = self.client.post(url, data_formset)

        details = json.loads(r.content)
        upload_hash = details['upload_hash']

        # Create and post with the formset.
        fields = []
        for i in range(amount):
            fields.append(self.formset_new_form(caption='hi',
                                                upload_hash=upload_hash,
                                                position=i))
        data_formset = self.formset_media(*fields)

        self.media_edit_url

        r = self.client.post(self.media_edit_url, data_formset)

    def test_edit_media_preview_add(self):
        self.preview_add()

        eq_(str(self.get_addon().previews.all()[0].caption), 'hi')

    def test_edit_media_preview_edit(self):
        self.preview_add()
        preview = self.get_addon().previews.all()[0]
        edited = {'caption': 'bye',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': preview.position,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.media_edit_url, data_formset)

        eq_(str(self.get_addon().previews.all()[0].caption), 'bye')
        eq_(len(self.get_addon().previews.all()), 1)

    def test_edit_media_preview_reorder(self):
        self.preview_add(3)

        previews = self.get_addon().previews.all()

        base = dict(upload_hash='', file_upload=None)

        # Three preview forms were generated; mix them up here.
        a = dict(caption="first", position=1, id=previews[2].id)
        b = dict(caption="second", position=2, id=previews[0].id)
        c = dict(caption="third", position=3, id=previews[1].id)
        a.update(base)
        b.update(base)
        c.update(base)

        # Add them in backwards ("third", "second", "first")
        data_formset = self.formset_media(c, b, a, initial_count=3)
        eq_(data_formset['files-0-caption'], 'third')
        eq_(data_formset['files-1-caption'], 'second')
        eq_(data_formset['files-2-caption'], 'first')

        self.client.post(self.media_edit_url, data_formset)

        # They should come out "first", "second", "third"
        eq_(self.get_addon().previews.all()[0].caption, 'first')
        eq_(self.get_addon().previews.all()[1].caption, 'second')
        eq_(self.get_addon().previews.all()[2].caption, 'third')

    def test_edit_media_preview_delete(self):
        self.preview_add()
        preview = self.get_addon().previews.get()
        edited = {'DELETE': 'checked',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': 0,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.media_edit_url, data_formset)

        eq_(len(self.get_addon().previews.all()), 0)

    def test_edit_media_preview_add_another(self):
        self.preview_add()
        self.preview_add()

        eq_(len(self.get_addon().previews.all()), 2)

    def test_edit_media_preview_add_two(self):
        self.preview_add(2)

        eq_(len(self.get_addon().previews.all()), 2)


class TestEditDetails(TestEdit):

    def setUp(self):
        super(TestEditDetails, self).setUp()
        self.details_url = self.get_url('details')
        self.details_edit_url = self.get_url('details', edit=True)

    def get_dict(self, **kw):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US',
                    homepage='http://twitter.com/fligtarsmom',
                    privacy_policy="fligtar's mom does <em>not</em> share your"
                                   " data with third parties.")
        data.update(kw)
        return data

    def test_edit(self):
        data = self.get_dict()
        r = self.client.post(self.details_edit_url, data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_xss(self):
        """
        Let's try to put xss in our description, and safe html, and verify
        that we are playing safe.
        """
        self.addon.description = ("This\n<b>IS</b>"
                                  "<script>alert('awesome')</script>")
        self.addon.save()
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#edit-addon-details span[lang]').html(),
                "This<br/><b>IS</b>&lt;script&gt;alert('awesome')"
                '&lt;/script&gt;')

    def test_privacy_policy_xss(self):
        self.addon.privacy_policy = ("We\n<b>own</b>your"
                                     "<script>alert('soul')</script>")
        self.addon.save()
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#addon-privacy-policy span[lang]').html(),
                "We<br/><b>own</b>your&lt;script&gt;"
                "alert('soul')&lt;/script&gt;")

    def test_edit_exclude_optional_fields(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US', homepage='',
                    privacy_policy='we sell your data to everyone')

        r = self.client.post(self.details_edit_url, data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        da = dict(description=unicode(self.addon.description),
                  homepage=unicode(self.addon.homepage),
                  privacy_policy='your data is delicious')
        # TODO: description should get fixed up with the form.
        fields = ['description', 'name', 'summary']
        error = ('Before changing your default locale you must have a name, '
                 'summary, and description in that locale. '
                 'You are missing %s.')
        missing = lambda f: error % ', '.join(map(repr, f))

        da.update(default_locale='fr')
        r = self.client.post(self.details_edit_url, da)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a name.
        self.addon.name = {'fr': 'fr name'}
        self.addon.save()
        fields.remove('name')
        r = self.client.post(self.details_edit_url, da)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a summary.
        self.addon.summary = {'fr': 'fr summary'}
        self.addon.save()
        fields.remove('summary')
        r = self.client.post(self.details_edit_url, da)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we're sending an fr description with the form.
        da['description_fr'] = 'fr description'
        r = self.client.post(self.details_edit_url, da)
        eq_(r.context['form'].errors, {})

    def test_edit_default_locale_frontend_error(self):
        da = dict(description='xx', homepage='http://google.com',
                  default_locale='fr', privacy_policy='pp')
        rp = self.client.post(self.details_edit_url, da)
        self.assertContains(rp, 'Before changing your default locale you must')

    def test_edit_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')
        r = self.client.get(self.details_url)
        eq_(pq(r.content)('.addon_edit_locale').eq(0).text(), 'English (US)')

    def test_homepage_url_optional(self):
        r = self.client.post(self.details_edit_url, self.get_dict(homepage=''))
        self.assertNoFormErrors(r)

    def test_homepage_url_invalid(self):
        r = self.client.post(self.details_edit_url,
                             self.get_dict(homepage='xxx'))
        self.assertFormError(r, 'form', 'homepage', 'Enter a valid URL.')


class TestEditSupport(TestEdit):

    def setUp(self):
        super(TestEditSupport, self).setUp()
        self.support_url = self.get_url('support')
        self.support_edit_url = self.get_url('support', edit=True)

    def test_edit_support(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='http://apple.com/')

        r = self.client.post(self.support_edit_url, data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_support_premium(self):
        self.get_addon().update(premium_type=amo.ADDON_PREMIUM)
        data = dict(support_email='sjobs@apple.com',
                    support_url='')
        r = self.client.post(self.support_edit_url, data)
        eq_(r.context['form'].errors, {})
        eq_(self.get_addon().support_email, data['support_email'])

    def test_edit_support_premium_required(self):
        self.get_addon().update(premium_type=amo.ADDON_PREMIUM)
        data = dict(support_url='')
        r = self.client.post(self.support_edit_url, data)
        assert 'support_email' in r.context['form'].errors

    def test_edit_support_getsatisfaction(self):
        urls = [("http://getsatisfaction.com/abc/products/def", 'abcdef'),
                ("http://getsatisfaction.com/abc/", 'abc'),  # No company
                ("http://google.com", None)]  # Delete GS

        for (url, val) in urls:
            data = dict(support_email='abc@def.com', support_url=url)

            r = self.client.post(self.support_edit_url, data)
            eq_(r.context['form'].errors, {})

            result = pq(r.content)('.addon_edit_gs').eq(0).text()
            doc = pq(r.content)
            result = doc('.addon_edit_gs').eq(0).text()

            result = re.sub('\W', '', result) if result else None

            eq_(result, val)

    def test_edit_support_optional_url(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='')

        r = self.client.post(self.support_edit_url, data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_support_optional_email(self):
        data = dict(support_email='',
                    support_url='http://apple.com/')

        r = self.client.post(self.support_edit_url, data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])


class TestEditTechnical(TestEdit):
    fixtures = TestEdit.fixtures + ['addons/persona', 'base/addon_40',
                                    'base/addon_1833_yoono',
                                    'base/addon_4664_twitterbar.json',
                                    'base/addon_5299_gcal', 'base/addon_6113']

    def setUp(self):
        super(TestEditTechnical, self).setUp()
        self.technical_url = self.get_url('technical')
        self.technical_edit_url = self.get_url('technical', edit=True)

    def formset(self, data):
        return formset(**data)

    def test_log(self):
        data = self.formset({'developer_comments': 'This is a test'})
        o = ActivityLog.objects
        eq_(o.count(), 0)
        r = self.client.post(self.technical_edit_url, data)
        eq_(r.context['form'].errors, {})
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_technical_on(self):
        # Turn everything on
        data = dict(developer_comments='Test comment!',
                    external_software='on',
                    site_specific='on',
                    view_source='on')

        r = self.client.post(self.technical_edit_url, self.formset(data))
        eq_(r.context['form'].errors, {})

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                eq_(unicode(getattr(addon, k)), unicode(data[k]))
            else:
                eq_(getattr(addon, k), True if data[k] == 'on' else False)

        # Andddd offf
        data = dict(developer_comments='Test comment!')
        r = self.client.post(self.technical_edit_url, self.formset(data))
        addon = self.get_addon()

        eq_(addon.external_software, False)
        eq_(addon.site_specific, False)
        eq_(addon.view_source, False)

    def test_technical_devcomment_notrequired(self):
        data = dict(developer_comments='',
                    external_software='on',
                    site_specific='on',
                    view_source='on')
        r = self.client.post(self.technical_edit_url, self.formset(data))
        eq_(r.context['form'].errors, {})

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                eq_(unicode(getattr(addon, k)), unicode(data[k]))
            else:
                eq_(getattr(addon, k), True if data[k] == 'on' else False)


class TestAdmin(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def login_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def login_user(self):
        assert self.client.login(username='del@icio.us', password='password')

    def test_show_admin_settings_admin(self):
        self.login_admin()
        url = reverse('mkt.developers.addons.edit', args=['a3615'])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        self.assertContains(r, 'Admin Settings')

    def test_show_admin_settings_nonadmin(self):
        self.login_user()
        url = reverse('mkt.developers.addons.edit', args=['a3615'])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        self.assertNotContains(r, 'Admin Settings')

    def test_post_as_admin(self):
        self.login_admin()
        url = reverse('mkt.developers.addons.admin', args=['a3615'])
        r = self.client.post(url)
        eq_(r.status_code, 200)

    def test_post_as_nonadmin(self):
        self.login_user()
        url = reverse('mkt.developers.addons.admin', args=['a3615'])
        r = self.client.post(url)
        eq_(r.status_code, 403)
