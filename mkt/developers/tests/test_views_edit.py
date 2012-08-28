import json
import os
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
from nose import SkipTest
from nose.tools import eq_
from PIL import Image
from pyquery import PyQuery as pq
from tower import strip_whitespace
from waffle.models import Switch

import amo
import amo.tests
from access.models import GroupUser, Group
from amo.tests import assert_required, formset, initial
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.forms import AddonFormBasic
from addons.models import (Addon, AddonCategory, AddonDeviceType, AddonUser,
                           Category)
from constants.applications import DEVICE_TYPES
from lib.video.tests import files as video_files
from users.models import UserProfile

import mkt
from mkt.constants.ratingsbodies import RATINGS_BODIES
from mkt.developers.models import ActivityLog
from mkt.webapps.models import AddonExcludedRegion as AER, ContentRating

response_mock = mock.Mock()
response_mock.read.return_value = '''
    {
        "name": "Something Ballin!",
        "description": "Goin' hard in the paint.",
        "launch_path": "/ballin/4.eva",
        "developer": {
            "name": "Pro Balliner",
            "url": "http://www.ballin4eva.xxx"
        },
        "icons": {
            "128": "/ballin/icon.png"
        },
        "installs_allowed_from": [ "https://marketplace.mozilla.org" ]
    }
'''


def get_section_url(addon, section, edit=False):
    args = [addon.app_slug, section]
    if edit:
        args.append('edit')
    return reverse('mkt.developers.apps.section', args=args)


class TestEdit(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url()
        self.user = UserProfile.objects.get(username='31337')
        assert self.client.login(username=self.user.email, password='password')

    def get_webapp(self):
        return Addon.objects.no_cache().get(id=337141)

    def get_url(self, section, edit=False):
        return get_section_url(self.webapp, section, edit)

    def get_dict(self, **kw):
        fs = formset(self.cat_initial, initial_count=1)
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary'}
        result.update(**kw)
        result.update(fs)
        return result

    def compare(self, data):
        """Compare an app against a `dict` of expected values."""
        mapping = {
            'regions': 'get_region_ids'
        }

        webapp = self.get_webapp()
        for k, v in data.iteritems():
            k = mapping.get(k, k)

            val = getattr(webapp, k, '')
            if callable(val):
                val = val()

            eq_(unicode(val), unicode(v))

    def check_form_url(self, section):
        # Check form destinations and "Edit" button.
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('form').attr('action'), self.edit_url)
        eq_(doc('h2 .button').attr('data-editurl'), self.edit_url)

        # Check "Cancel" button.
        r = self.client.get(self.edit_url)
        eq_(pq(r.content)('form .addon-edit-cancel').attr('href'), self.url)


class TestEditListingWebapp(TestEdit):
    fixtures = TestEdit.fixtures

    @mock.patch.object(settings, 'APP_PREVIEW', False)
    def test_apps_context(self):
        r = self.client.get(self.url)
        eq_(r.context['webapp'], True)
        eq_(pq(r.content)('title').text(),
            'Edit Listing | %s | Firefox Marketplace' % self.webapp.name)

    def test_nav_links(self):
        r = self.client.get(self.url)
        doc = pq(r.content)('#edit-addon-nav')
        eq_(doc.length, 1)
        eq_(doc('.view-stats').length, 0)


@mock.patch.object(settings, 'TASK_USER_ID', 999)
class TestEditBasic(TestEdit):
    fixtures = TestEdit.fixtures

    def setUp(self):
        super(TestEditBasic, self).setUp()
        Switch.objects.create(name='marketplace', active=True)
        self.cat = Category.objects.create(name='Games', type=amo.ADDON_WEBAPP)
        self.dtype = DEVICE_TYPES.keys()[0]
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=self.dtype)
        self.url = self.get_url('basic')
        self.edit_url = self.get_url('basic', edit=True)

    def get_webapp(self):
        return Addon.objects.get(id=337141)

    def get_dict(self, **kw):
        result = {'device_types': self.dtype, 'name': 'new name',
                  'slug': 'test_slug', 'summary': 'new summary',
                  'manifest_url': self.get_webapp().manifest_url,
                  'categories': [self.cat.id]}
        result.update(**kw)
        return result

    def test_form_url(self):
        self.check_form_url('basic')

    def test_apps_context(self):
        eq_(self.client.get(self.url).context['webapp'], True)

    def test_appslug_visible(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#slug_edit').remove('a, em').text(),
            u'/\u2026/%s' % self.webapp.app_slug)

    def test_edit_name_required(self):
        r = self.client.post(self.edit_url, self.get_dict(name=''))
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_required_for_all_whitespace(self):
        r = self.client.post(self.edit_url, self.get_dict(name='  \t  \n  '))
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_max_length(self):
        r = self.client.post(self.edit_url, self.get_dict(name='x' * 129))
        eq_(list(r.context['form'].errors['name']),
            [('en-us',
              'Ensure this value has at most 128 characters (it has 129).')])

    def test_edit_slug_success(self):
        data = self.get_dict()
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        eq_(r.status_code, 200)
        webapp = self.get_webapp()
        eq_(webapp.app_slug, data['slug'])
        # Make sure only the app_slug changed.
        eq_(webapp.slug, self.webapp.slug)

    def test_edit_slug_max_length(self):
        r = self.client.post(self.edit_url, self.get_dict(slug='x' * 31))
        self.assertFormError(r, 'form', 'slug',
            'Ensure this value has at most 30 characters (it has 31).')

    def test_edit_slug_dupe(self):
        Addon.objects.create(type=amo.ADDON_WEBAPP, app_slug='dupe')
        r = self.client.post(self.edit_url, self.get_dict(slug='dupe'))
        self.assertFormError(r, 'form', 'slug', 'This slug is already in use.')
        webapp = self.get_webapp()
        # Nothing changed.
        eq_(webapp.slug, self.webapp.slug)
        eq_(webapp.app_slug, self.webapp.app_slug)

    def test_view_manifest_url_default(self):
        # Should be able to see manifest URL listed.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#manifest-url a').attr('href'),
            self.webapp.manifest_url)

        # There should be a readonly text field.
        r = self.client.get(self.edit_url)
        row = pq(r.content)('#manifest-url')
        eq_(row.find('input[name=manifest_url][readonly]').length, 1)

        # POST with the new manifest URL.
        url = 'https://ballin.com/ballin4eva'
        r = self.client.post(self.edit_url, self.get_dict(manifest_url=url))
        self.assertNoFormErrors(r)

        # The manifest should remain unchanged since this is disabled for
        # non-admins.
        eq_(self.get_webapp().manifest_url, self.webapp.manifest_url)

    def test_view_edit_manifest_url_empty(self):
        # Empty manifest should throw an error.
        url = ''
        r = self.client.post(self.edit_url, self.get_dict(manifest_url=url))
        form = r.context['form']
        assert 'manifest_url' in form.errors
        assert 'This field is required' in form.errors['manifest_url'][0]

    @mock.patch('devhub.tasks.urllib2.urlopen')
    def test_view_admin_edit_manifest_url(self, mock_urlopen):
        mock_urlopen.return_value = response_mock

        self.client.login(username='admin@mozilla.com', password='password')
        # Should be able to see manifest URL listed.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#manifest-url a').attr('href'),
            self.webapp.manifest_url)

        # Admins can edit the manifest URL and should see a text field.
        r = self.client.get(self.edit_url)
        row = pq(r.content)('#manifest-url')
        eq_(row.find('input[name=manifest_url]').length, 1)
        eq_(row.find('input[name=manifest_url][readonly]').length, 0)

        # POST with the new manifest URL.
        url = 'https://ballin.com/ballin4eva.webapp'
        r = self.client.post(self.edit_url, self.get_dict(manifest_url=url))
        self.assertNoFormErrors(r)

        self.webapp = self.get_webapp()
        eq_(self.webapp.manifest_url, url)
        eq_(self.webapp.app_domain, 'https://ballin.com')
        eq_(self.webapp.current_version.version, '1.0')
        eq_(self.webapp.versions.count(), 1)

    @mock.patch('devhub.tasks.urllib2.urlopen')
    def test_view_manifest_changed_dupe_app_domain(self, mock_urlopen):
        mock_urlopen.return_value = response_mock
        Switch.objects.create(name='webapps-unique-by-domain', active=True)
        amo.tests.app_factory(name='Super Duper',
                              app_domain='https://ballin.com')

        self.client.login(username='admin@mozilla.com', password='password')
        # POST with the new manifest URL.
        url = 'https://ballin.com/ballin4eva.webapp'
        r = self.client.post(self.edit_url, self.get_dict(manifest_url=url))
        form = r.context['form']
        assert 'manifest_url' in form.errors
        assert 'one app per domain' in form.errors['manifest_url'][0]

        eq_(self.get_webapp().manifest_url, self.webapp.manifest_url,
            'Manifest URL should not have been changed!')

    @mock.patch('devhub.tasks.urllib2.urlopen')
    def test_view_manifest_changed_same_domain_diff_path(self, mock_urlopen):
        mock_urlopen.return_value = response_mock
        Switch.objects.create(name='webapps-unique-by-domain', active=True)
        self.client.login(username='admin@mozilla.com', password='password')
        # POST with the new manifest URL for same domain but w/ different path.
        data = self.get_dict(manifest_url=self.webapp.manifest_url + 'xxx')
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        eq_(self.get_webapp().manifest_url, self.webapp.manifest_url + 'xxx',
            'Manifest URL should have changed!')

    def test_view_manifest_url_changed(self):
        new_url = 'http://omg.org/yes'
        self.webapp.manifest_url = new_url
        self.webapp.save()

        # If we change the `manifest_url` manually, the URL here should change.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#manifest-url a').attr('href'), new_url)

    def test_categories_listed(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#addon-categories-edit').text(),
            unicode(self.cat.name))

        r = self.client.post(self.url)
        eq_(pq(r.content)('#addon-categories-edit').text(),
            unicode(self.cat.name))

    def test_edit_categories_add(self):
        new = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        cats = [self.cat.id, new.id]
        self.client.post(self.edit_url, self.get_dict(categories=cats))
        app_cats = self.get_webapp().categories.values_list('id', flat=True)
        eq_(sorted(app_cats), cats)

    def test_edit_categories_addandremove(self):
        new = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        cats = [new.id]
        self.client.post(self.edit_url, self.get_dict(categories=cats))
        app_cats = self.get_webapp().categories.values_list('id', flat=True)
        eq_(sorted(app_cats), cats)

    def test_edit_categories_required(self):
        r = self.client.post(self.edit_url, self.get_dict(categories=[]))
        assert_required(r.context['cat_form'].errors['categories'][0])

    def test_edit_categories_xss(self):
        new = Category.objects.create(name='<script>alert("xss");</script>',
                                      type=amo.ADDON_WEBAPP)
        cats = [self.cat.id, new.id]
        r = self.client.post(self.edit_url, self.get_dict(categories=cats))

        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content

    def test_edit_categories_nonexistent(self):
        r = self.client.post(self.edit_url, self.get_dict(categories=[100]))
        eq_(r.context['cat_form'].errors['categories'],
            ['Select a valid choice. 100 is not one of the available '
             'choices.'])

    def test_edit_categories_max(self):
        new1 = Category.objects.create(name='Books', type=amo.ADDON_WEBAPP)
        new2 = Category.objects.create(name='Lifestyle', type=amo.ADDON_WEBAPP)
        cats = [self.cat.id, new1.id, new2.id]

        r = self.client.post(self.edit_url, self.get_dict(categories=cats))
        eq_(r.context['cat_form'].errors['categories'],
            ['You can have only 2 categories.'])

    def test_exclude_games_in_brazil(self):
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')

        r = self.client.post(self.edit_url,
                             self.get_dict(categories=[games.id]))
        self.assertNoFormErrors(r)
        eq_(list(AER.objects.values_list('region', flat=True)),
            [mkt.regions.BR.id])

    def test_games_already_excluded_in_brazil(self):
        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')

        r = self.client.post(self.edit_url,
                             self.get_dict(categories=[games.id]))
        self.assertNoFormErrors(r)
        eq_(list(AER.objects.values_list('region', flat=True)),
            [mkt.regions.BR.id])

    def test_edit_other_categories_are_not_excluded(self):
        # Keep the category around for good measure.
        Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')

        r = self.client.post(self.url, self.get_dict())
        self.assertNoFormErrors(r)
        eq_(AER.objects.count(), 0)

    def test_devices_listed(self):
        r = self.client.post(self.url, self.get_dict())
        eq_(pq(r.content)('#addon-device-types-edit').text(),
            DEVICE_TYPES[self.dtype].name)

    def test_edit_devices_add(self):
        new = DEVICE_TYPES.keys()[1]
        data = self.get_dict()
        data['device_types'] = [self.dtype, new]
        self.client.post(self.edit_url, data)
        devicetypes = self.get_webapp().device_types
        eq_([d.id for d in devicetypes], list(data['device_types']))

    def test_edit_devices_addandremove(self):
        new = DEVICE_TYPES.keys()[1]
        data = self.get_dict()
        data['device_types'] = [new]
        self.client.post(self.edit_url, data)
        devicetypes = self.get_webapp().device_types
        eq_([d.id for d in devicetypes], list(data['device_types']))

    def test_edit_devices_add_required(self):
        data = self.get_dict()
        data['device_types'] = []
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'device_type_form', 'device_types',
                             'This field is required.')

    def test_edit_summary_max_length(self):
        r = self.client.post(self.edit_url, self.get_dict(summary='x' * 251))
        eq_(list(r.context['form'].errors['summary']),
            [('en-us',
              'Ensure this value has at most 250 characters (it has 251).')])

    def test_edit(self):
        old_name = self.webapp.name
        data = self.get_dict()

        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)
        webapp = self.get_webapp()

        eq_(unicode(webapp.name), data['name'])
        eq_(webapp.name.id, old_name.id)
        eq_(unicode(webapp.app_slug), data['slug'])
        eq_(unicode(webapp.summary), data['summary'])

    def test_edit_check_description(self):
        # Make sure bug 629779 doesn't return.
        r = self.client.post(self.edit_url, self.get_dict())
        eq_(r.status_code, 200)

        eq_(self.get_webapp().description, self.webapp.description)

    def test_edit_slug_invalid(self):
        r = self.client.post(self.edit_url,
                             self.get_dict(name='', slug='invalid'))
        eq_(pq(r.content)('form').attr('action'), self.edit_url)

    def test_edit_slug_valid(self):
        old_edit = self.edit_url
        data = self.get_dict(slug='valid')
        r = self.client.post(self.edit_url, data)
        doc = pq(r.content)
        assert doc('form').attr('action') != old_edit

    def test_edit_summary_escaping(self):
        data = self.get_dict(summary='<b>oh my</b>')
        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)

        # Fetch the page so the LinkifiedTranslation gets in cache.
        webapp = self.get_webapp()
        r = self.client.get(webapp.get_dev_url('edit'))
        eq_(pq(r.content)('[data-name=summary]').html().strip(),
            '<span lang="en-us">&lt;b&gt;oh my&lt;/b&gt;</span>')

        # Now make sure we don't have escaped content in the rendered form.
        form = AddonFormBasic(instance=webapp, request=object())
        eq_(pq('<body>%s</body>' % form['summary'])('[lang="en-us"]').html(),
            data['summary'])

    def test_edit_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')
        data = self.get_dict()
        r = self.client.post(self.edit_url, data)
        # Make sure we get errors when they are just regular users.
        eq_(r.status_code, 403)

        AddonUser.objects.create(addon=self.webapp, user_id=999,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)
        webapp = self.get_webapp()

        eq_(unicode(webapp.name), data['name'])
        eq_(unicode(webapp.app_slug), data['slug'])
        eq_(unicode(webapp.summary), data['summary'])

    def get_l10n_urls(self):
        return [self.webapp.get_dev_url(p) for p in ('edit', 'profile')]

    def test_l10n(self):
        self.webapp.update(default_locale='en-US')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'en-us',
                'l10n menu not visible for %s' % url)

    def test_l10n_not_us(self):
        self.webapp.update(default_locale='fr')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr',
                'l10n menu not visible for %s' % url)

    def test_l10n_not_us_id_url(self):
        self.skip_if_disabled(settings.REGION_STORES)
        self.webapp.update(default_locale='fr')
        for url in self.get_l10n_urls():
            r = self.client.get('/id' + url, follow=True)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr',
                'l10n menu not visible for %s' % url)

    @mock.patch('mkt.developers.views._update_manifest')
    def test_refresh(self, fetch):
        self.client.login(username='steamcube@mozilla.com',
                          password='password')
        url = reverse('mkt.developers.apps.refresh_manifest',
                      args=[self.webapp.app_slug])
        r = self.client.post(url)
        eq_(r.status_code, 204)
        fetch.assert_called_once_with(self.webapp.pk)

    @mock.patch('mkt.developers.views._update_manifest')
    def test_refresh_dev_only(self, fetch):
        self.client.login(username='regular@mozilla.com',
                          password='password')
        url = reverse('mkt.developers.apps.refresh_manifest',
                      args=[self.webapp.app_slug])
        r = self.client.post(url)
        eq_(r.status_code, 403)
        eq_(fetch.called, 0)


class TestEditMedia(TestEdit):

    def setUp(self):
        super(TestEditMedia, self).setUp()
        self.url = self.get_url('media')
        self.edit_url = self.get_url('media', True)
        self.icon_upload = self.webapp.get_dev_url('upload_icon')
        self.preview_upload = self.webapp.get_dev_url('upload_preview')
        patches = {
            'ADDON_ICONS_PATH': tempfile.mkdtemp(),
            'PREVIEW_THUMBNAIL_PATH': tempfile.mkstemp()[1] + '%s/%d.png',
        }
        for k, v in patches.iteritems():
            patcher = mock.patch.object(settings, k, v)
            patcher.start()
            self.addCleanup(patcher.stop)

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.edit_url).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, blank_kw=None, *args, **kw):
        blank_kw = blank_kw or {}
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form(**blank_kw)],
                     **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def new_preview_hash(self):
        # At least one screenshot is required.
        src_image = open(get_image_path('mozilla.png'), 'rb')
        r = self.client.post(self.preview_upload,
                             dict(upload_image=src_image))
        return {'upload_hash': json.loads(r.content)['upload_hash']}

    def test_form_url(self):
        self.check_form_url('media')

    def test_edit_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(blank_kw=self.new_preview_hash(),
                                          **data)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)
        webapp = self.get_webapp()

        assert webapp.get_icon_url(128).endswith('icons/default-128.png')
        assert webapp.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            eq_(unicode(getattr(webapp, k)), data[k])

    def test_edit_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(blank_kw=self.new_preview_hash(),
                                          **data)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)
        webapp = self.get_webapp()

        assert webapp.get_icon_url(64).endswith('icons/appearance-64.png')
        assert webapp.get_icon_url(128).endswith('icons/appearance-128.png')

        for k in data:
            eq_(unicode(getattr(webapp, k)), data[k])

    def test_edit_uploadedicon(self):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        response = self.client.post(self.icon_upload,
                                    dict(upload_image=src_image))
        response_json = json.loads(response.content)
        webapp = self.get_webapp()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(blank_kw=self.new_preview_hash(),
                                          **data)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)
        webapp = self.get_webapp()

        # Unfortunate hardcoding of URL
        url = webapp.get_icon_url(64)
        assert ('addon_icons/%s/%s' % (webapp.id / 1000, webapp.id)) in url, (
            'Unexpected path: %r' % url)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (webapp.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % webapp.id)

        eq_(storage.exists(dest), True)

        eq_(Image.open(storage.open(dest)).size, (32, 12))

    def test_edit_icon_log(self):
        self.test_edit_uploadedicon()
        log = ActivityLog.objects.all()
        eq_(log.count(), 1)
        eq_(log[0].action, amo.LOG.CHANGE_ICON.id)

    def test_edit_uploadedicon_noresize(self):
        img = '%s/img/notifications/error.png' % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        webapp = self.get_webapp()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(blank_kw=self.new_preview_hash(),
                                          **data)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)
        webapp = self.get_webapp()

        # Unfortunate hardcoding of URL
        addon_url = webapp.get_icon_url(64).split('?')[0]
        end = 'addon_icons/%s/%s-64.png' % (webapp.id / 1000, webapp.id)
        assert addon_url.endswith(end), 'Unexpected path: %r' % addon_url

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (webapp.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % webapp.id)

        assert storage.exists(dest)

        eq_(Image.open(storage.open(dest)).size, (48, 48))

    def test_no_video_types(self):
        res = self.client.get(self.get_url('media', edit=True))
        doc = pq(res.content)
        eq_(doc('.screenshot_upload').attr('data-allowed-types'),
            'image/jpeg|image/png')
        eq_(doc('#id_icon_upload').attr('data-allowed-types'),
            'image/jpeg|image/png')

    def test_video_types(self):
        Switch.objects.create(name='video-upload', active=True)
        res = self.client.get(self.get_url('media', edit=True))
        doc = pq(res.content)
        eq_(doc('.screenshot_upload').attr('data-allowed-types'),
            'image/jpeg|image/png|video/webm')

    def check_image_type(self, url, msg):
        img = '%s/js/zamboni/devhub.js' % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        res = self.client.post(url, {'upload_image': src_image})
        response_json = json.loads(res.content)
        eq_(response_json['errors'][0], msg)

    # The check_image_type method uploads js, so let's try sending that
    # to ffmpeg to see what it thinks.
    @mock.patch.object(amo, 'VIDEO_TYPES', ['application/javascript'])
    def test_edit_video_wrong_type(self):
        raise SkipTest
        # TODO(andym): fix this.
        Switch.objects.create(name='video-upload', active=True)
        self.check_image_type(self.preview_upload, 'Videos must be in WebM.')

    def test_edit_icon_wrong_type(self):
        self.check_image_type(self.icon_upload,
                              'Icons must be either PNG or JPG.')

    def test_edit_screenshot_wrong_type(self):
        self.check_image_type(self.preview_upload,
                              'Images must be either PNG or JPG.')

    def setup_image_status(self):
        self.icon_dest = os.path.join(self.webapp.get_icon_dir(),
                                      '%s-64.png' % self.webapp.id)
        os.makedirs(os.path.dirname(self.icon_dest))
        open(self.icon_dest, 'w')

        self.preview = self.webapp.previews.create()
        self.preview.save()
        os.makedirs(os.path.dirname(self.preview.thumbnail_path))
        open(self.preview.thumbnail_path, 'w')

        self.url = self.webapp.get_dev_url('ajax.image.status')

    def test_icon_status_no_choice(self):
        self.webapp.update(icon_type='')
        url = self.webapp.get_dev_url('ajax.image.status')
        result = json.loads(self.client.get(url).content)
        assert result['icons']

    def test_icon_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_icon_status_fails(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        result = json.loads(self.client.get(self.url).content)
        assert not result['icons']

    def test_preview_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

        # No previews means that all the images are done.
        self.webapp.previews.all().delete()
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
        self.webapp.update(type=amo.ADDON_PERSONA)
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_default(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        self.webapp.update(icon_type='icon/photos')
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def check_image_animated(self, url, msg):
        filehandle = open(get_image_path('animated.png'), 'rb')

        res = self.client.post(url, {'upload_image': filehandle})
        response_json = json.loads(res.content)
        eq_(response_json['errors'][0], msg)

    def test_icon_animated(self):
        self.check_image_animated(self.icon_upload,
                                  'Icons cannot be animated.')

    def test_screenshot_animated(self):
        self.check_image_animated(self.preview_upload,
                                  'Images cannot be animated.')

    @mock.patch('lib.video.ffmpeg.Video')
    def add(self, handle, Video, num=1):
        data_formset = self.formset_media(upload_image=handle)
        r = self.client.post(self.preview_upload, data_formset)
        self.assertNoFormErrors(r)
        upload_hash = json.loads(r.content)['upload_hash']

        # Create and post with the formset.
        fields = []
        for i in xrange(num):
            fields.append(self.formset_new_form(caption='hi',
                                                upload_hash=upload_hash,
                                                position=i))
        data_formset = self.formset_media(*fields)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)

    def preview_add(self, num=1):
        self.add(open(get_image_path('mozilla.png'), 'rb'), num=num)

    def preview_video_add(self, num=1):
        self.add(open(video_files['good'], 'rb'), num=num)

    @mock.patch('lib.video.ffmpeg.Video')
    def add_json(self, handle, Video):
        data_formset = self.formset_media(upload_image=handle)
        result = self.client.post(self.preview_upload, data_formset)
        return json.loads(result.content)

    def test_edit_preview_video_add_hash(self):
        Switch.objects.create(name='video-upload', active=True)
        res = self.add_json(open(video_files['good'], 'rb'))
        assert res['upload_hash'].endswith('.video-webm')

    def test_edit_preview_video_add_hash_switch_off(self):
        res = self.add_json(open(video_files['good'], 'rb'))
        eq_(res['errors'], [u'Images must be either PNG or JPG.'])

    def test_edit_preview_add_hash(self):
        res = self.add_json(open(get_image_path('mozilla.png'), 'rb'))
        assert res['upload_hash'].endswith('.image-png')

    @mock.patch.object(settings, 'MAX_VIDEO_UPLOAD_SIZE', 1)
    def test_edit_preview_video_size(self):
        Switch.objects.create(name='video-upload', active=True)
        res = self.add_json(open(video_files['good'], 'rb'))
        assert res['errors'][0].startswith('Please use')

    @mock.patch('lib.video.tasks.resize_video')
    def test_edit_preview_video_add(self, resize_video):
        Switch.objects.create(name='video-upload', active=True)
        self.preview_video_add()
        eq_(str(self.get_webapp().previews.all()[0].caption), 'hi')

    def test_edit_preview_video_add_switch_off(self):
        self.assertRaises(AssertionError, self.preview_video_add)

    def test_edit_preview_add(self):
        self.preview_add()
        eq_(str(self.get_webapp().previews.all()[0].caption), 'hi')

    def test_edit_preview_edit(self):
        self.preview_add()
        preview = self.get_webapp().previews.all()[0]
        edited = {'caption': 'bye',
                  'upload_hash': 'xxx',
                  'id': preview.id,
                  'position': preview.position,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.edit_url, data_formset)

        previews = self.get_webapp().previews
        eq_(str(previews.all()[0].caption), 'bye')
        eq_(previews.count(), 1)

    def test_edit_preview_reorder(self):
        self.preview_add(3)

        previews = self.get_webapp().previews.all()

        base = dict(upload_hash='xxx', file_upload=None)

        # Three preview forms were generated; mix them up here.
        a = dict(caption='first', position=1, id=previews[2].id)
        b = dict(caption='second', position=2, id=previews[0].id)
        c = dict(caption='third', position=3, id=previews[1].id)
        a.update(base)
        b.update(base)
        c.update(base)

        # Add them in backwards ("third", "second", "first")
        data_formset = self.formset_media({}, *(c, b, a), initial_count=3)
        eq_(data_formset['files-0-caption'], 'third')
        eq_(data_formset['files-1-caption'], 'second')
        eq_(data_formset['files-2-caption'], 'first')

        self.client.post(self.edit_url, data_formset)

        # They should come out "first", "second", "third".
        eq_(self.get_webapp().previews.all()[0].caption, 'first')
        eq_(self.get_webapp().previews.all()[1].caption, 'second')
        eq_(self.get_webapp().previews.all()[2].caption, 'third')

    def test_edit_preview_delete(self):
        self.preview_add()
        self.preview_add()
        orig_previews = self.get_webapp().previews.all()

        # Delete second preview. Keep the first.
        edited = {'DELETE': 'checked',
                  'upload_hash': 'xxx',
                  'id': orig_previews[1].id,
                  'position': 0,
                  'file_upload': None}
        ctx = self.client.get(self.edit_url).context

        first = initial(ctx['preview_form'].forms[0])
        first['upload_hash'] = 'xxx'
        data_formset = self.formset_media(edited, *(first,), initial_count=2)

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)

        # First one should still be there.
        eq_(list(self.get_webapp().previews.all()), [orig_previews[0]])

    def test_edit_preview_add_another(self):
        self.preview_add()
        self.preview_add()
        eq_(self.get_webapp().previews.count(), 2)

    def test_edit_preview_add_two(self):
        self.preview_add(2)
        eq_(self.get_webapp().previews.count(), 2)

    def test_screenshot_required(self):
        r = self.client.post(self.edit_url, self.formset_media())
        eq_(r.context['preview_form'].non_form_errors(),
            ['You must upload at least one screenshot.'])

    def test_screenshot_video_required(self):
        Switch.objects.create(name='video-upload', active=True)
        r = self.client.post(self.edit_url, self.formset_media())
        eq_(r.context['preview_form'].non_form_errors(),
            ['You must upload at least one screenshot or video.'])

    def test_screenshot_with_icon(self):
        self.preview_add()
        preview = self.get_webapp().previews.all()[0]
        edited = {'upload_hash': '', 'id': preview.id}
        data_formset = self.formset_media(edited, initial_count=1)
        data_formset.update(icon_type='image/png', icon_upload_hash='')

        r = self.client.post(self.edit_url, data_formset)
        self.assertNoFormErrors(r)


class TestEditDetails(TestEdit):

    def setUp(self):
        super(TestEditDetails, self).setUp()
        self.url = self.get_url('details')
        self.edit_url = self.get_url('details', edit=True)

    def get_dict(self, **kw):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US',
                    homepage='http://twitter.com/fligtarsmom',
                    privacy_policy="fligtar's mom does <em>not</em> share "
                                   "your data with third parties.")
        if settings.REGION_STORES:
            data['regions'] = [mkt.regions.CA.id]
        data.update(kw)
        return data

    def get_excluded_ids(self):
        return sorted(AER.objects.filter(addon=self.webapp)
                         .values_list('region', flat=True))

    def test_form_url(self):
        self.check_form_url('details')

    def test_edit(self):
        data = self.get_dict()
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        self.compare(data)

    def test_edit_xss(self):
        """
        Let's try to put xss in our description, and safe html, and verify
        that we are playing safe.
        """
        self.webapp.description = ("This\n<b>IS</b>"
                                   "<script>alert('awesome')</script>")
        self.webapp.save()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#addon-description span[lang]').html(),
            "This<br/><b>IS</b>&lt;script&gt;alert('awesome')"
            '&lt;/script&gt;')

    def test_privacy_policy_xss(self):
        self.webapp.privacy_policy = ("We\n<b>own</b>your"
                                      "<script>alert('soul')</script>")
        self.webapp.save()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#addon-privacy-policy span[lang]').html(),
            "We<br/><b>own</b>your&lt;script&gt;"
            "alert('soul')&lt;/script&gt;")

    def test_edit_exclude_optional_fields(self):
        data = self.get_dict()
        data.update(description='New description with <em>html</em>!',
                    default_locale='en-US', homepage='',
                    privacy_policy='we sell your data to everyone')

        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        self.compare(data)

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        data = self.get_dict()
        data.update(description='bullocks',
                    homepage='http://omg.org/yes',
                    privacy_policy='your data is delicious')
        # TODO: description should get fixed up with the form.
        fields = ['description', 'name', 'summary']
        error = ('Before changing your default locale you must have a name, '
                 'summary, and description in that locale. '
                 'You are missing %s.')
        missing = lambda f: error % ', '.join(map(repr, f))

        data.update(default_locale='fr')
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a name.
        self.webapp.name = {'fr': 'fr name'}
        self.webapp.save()
        fields.remove('name')
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a summary.
        self.webapp.summary = {'fr': 'fr summary'}
        self.webapp.save()
        fields.remove('summary')
        r = self.client.post(self.edit_url, data)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we're sending an fr description with the form.
        data['description_fr'] = 'fr description'
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)

    def test_edit_default_locale_frontend_error(self):
        data = self.get_dict()
        data.update(description='xx', homepage='http://google.com',
                    default_locale='fr', privacy_policy='pp')
        rp = self.client.post(self.edit_url, data)
        self.assertContains(rp,
            'Before changing your default locale you must')

    def test_edit_locale(self):
        self.webapp.update(default_locale='en-US')
        r = self.client.get(self.url)
        eq_(pq(r.content)('.addon_edit_locale').eq(0).text(),
            'English (US)')

    def test_homepage_url_optional(self):
        r = self.client.post(self.edit_url, self.get_dict(homepage=''))
        self.assertNoFormErrors(r)

    def test_homepage_url_invalid(self):
        r = self.client.post(self.edit_url,
                             self.get_dict(homepage='xxx'))
        self.assertFormError(r, 'form', 'homepage', 'Enter a valid URL.')

    def test_regions_listed(self):
        self.skip_if_disabled(settings.REGION_STORES)
        r = self.client.get(self.url)
        eq_(strip_whitespace(pq(r.content)('#regions').text()),
            ', '.join([unicode(name) for id_, name in
                       mkt.regions.REGIONS_CHOICES_NAME[1:]]))

    def test_excluded_regions_not_listed(self):
        self.skip_if_disabled(settings.REGION_STORES)
        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)

        expected = [unicode(name) for id_, name in
                    mkt.regions.REGIONS_CHOICES_NAME[1:]
                    if id_ != mkt.regions.BR.id]

        r = self.client.get(self.url)
        eq_(strip_whitespace(pq(r.content)('#regions').text()),
            ', '.join(expected))

    def test_excluded_all_regions_not_listed(self):
        self.skip_if_disabled(settings.REGION_STORES)
        for region in mkt.regions.REGION_IDS:
            AER.objects.create(addon=self.webapp, region=region)

        r = self.client.get(self.url)
        eq_(pq(r.content)('#regions .empty').length, 1)

    def test_exclude_region(self):
        self.skip_if_disabled(settings.REGION_STORES)
        regions = list(mkt.regions.REGION_IDS)
        for region_id in regions:
            to_exclude = list(regions)
            to_exclude.remove(region_id)
            data = self.get_dict(regions=to_exclude, other_regions=True)
            r = self.client.post(self.edit_url, data)
            self.assertNoFormErrors(r)

            eq_(self.get_excluded_ids(), [region_id])

    def test_exclude_future_regions(self):
        self.skip_if_disabled(settings.REGION_STORES)
        data = self.get_dict(regions=mkt.regions.REGION_IDS,
                             other_regions=False)
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [mkt.regions.FUTURE.id])

    def test_include_regions(self):
        self.skip_if_disabled(settings.REGION_STORES)
        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)

        data = self.get_dict(regions=mkt.regions.REGION_IDS,
                             other_regions=True)
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [])

    def test_include_future_regions(self):
        self.skip_if_disabled(settings.REGION_STORES)
        AER.objects.create(addon=self.webapp, region=mkt.regions.FUTURE.id)

        data = self.get_dict(regions=mkt.regions.REGION_IDS,
                             other_regions=True)
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [])

    def test_include_all_and_future_regions(self):
        self.skip_if_disabled(settings.REGION_STORES)
        AER.objects.create(addon=self.webapp, region=mkt.regions.FUTURE.id)

        data = self.get_dict(regions=mkt.regions.REGION_IDS,
                             other_regions=True)
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [])

    def test_brazil_games_excluded(self):
        self.skip_if_disabled(settings.REGION_STORES)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        r = self.client.post(self.edit_url,
                             self.get_dict(regions=mkt.regions.REGION_IDS,
                                           other_regions=True))

        # Developers should still be able to save form OK, even
        # if they pass a bad region. Think of the grandfathered developers.
        self.assertNoFormErrors(r)

        # No matter what the developer tells us, still exclude Brazilian
        # games.
        eq_(self.get_excluded_ids(), [mkt.regions.BR.id])

    def test_brazil_games_already_excluded(self):
        self.skip_if_disabled(settings.REGION_STORES)

        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        r = self.client.post(self.edit_url,
                             self.get_dict(regions=mkt.regions.REGION_IDS,
                                           other_regions=True))
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [mkt.regions.BR.id])

    def test_brazil_games_with_content_rating(self):
        self.skip_if_disabled(settings.REGION_STORES)

        # This game has a government content rating!
        rb = mkt.regions.BR.ratingsbodies[0]
        ContentRating.objects.create(addon=self.webapp,
            ratings_body=rb.id, rating=rb.ratings[0].id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        r = self.client.post(self.edit_url,
                             self.get_dict(regions=mkt.regions.REGION_IDS,
                                           other_regions=True))
        self.assertNoFormErrors(r)

        eq_(self.get_excluded_ids(), [])

    def test_brazil_games_form_disabled(self):
        self.skip_if_disabled(settings.REGION_STORES)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        r = self.client.get(self.edit_url, self.get_dict())
        self.assertNoFormErrors(r)

        td = pq(r.content)('#regions')
        eq_(td.find('div[data-disabled]').attr('data-disabled'),
            json.dumps([mkt.regions.BR.id]))
        eq_(td.find('.note.disabled-regions').length, 1)

    def test_brazil_games_form_enabled_with_content_rating(self):
        self.skip_if_disabled(settings.REGION_STORES)

        rb = mkt.regions.BR.ratingsbodies[0]
        ContentRating.objects.create(addon=self.webapp,
            ratings_body=rb.id, rating=rb.ratings[0].id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        r = self.client.get(self.edit_url, self.get_dict())
        self.assertNoFormErrors(r)

        td = pq(r.content)('#regions')
        eq_(td.find('div[data-disabled]').attr('data-disabled'),
            json.dumps([]))
        eq_(td.find('.note.disabled-regions').length, 0)

    def test_brazil_other_cats_form_enabled(self):
        self.skip_if_disabled(settings.REGION_STORES)

        r = self.client.get(self.edit_url, self.get_dict())
        self.assertNoFormErrors(r)

        td = pq(r.content)('#regions')
        eq_(td.find('div[data-disabled]').attr('data-disabled'),
            json.dumps([]))
        eq_(td.find('.note.disabled-regions').length, 0)


class TestEditSupport(TestEdit):

    def setUp(self):
        super(TestEditSupport, self).setUp()
        self.url = self.get_url('support')
        self.edit_url = self.get_url('support', edit=True)

    def test_form_url(self):
        self.check_form_url('support')

    def test_edit_support(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='http://apple.com/')

        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        self.compare(data)

    def test_edit_support_free_required(self):
        r = self.client.post(self.edit_url, dict(support_url=''))
        self.assertFormError(r, 'form', 'support_email',
                             'This field is required.')

    def test_edit_support_premium_required(self):
        self.get_webapp().update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.post(self.edit_url, dict(support_url=''))
        self.assertFormError(r, 'form', 'support_email',
                             'This field is required.')

    def test_edit_support_premium(self):
        self.get_webapp().update(premium_type=amo.ADDON_PREMIUM)
        data = dict(support_email='sjobs@apple.com',
                    support_url='')
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        eq_(self.get_webapp().support_email, data['support_email'])

    def test_edit_support_url_optional(self):
        data = dict(support_email='sjobs@apple.com', support_url='')
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        self.compare(data)


class TestEditTechnical(TestEdit):
    fixtures = TestEdit.fixtures

    def setUp(self):
        super(TestEditTechnical, self).setUp()
        self.url = self.get_url('technical')
        self.edit_url = self.get_url('technical', edit=True)

    def test_form_url(self):
        self.check_form_url('technical')

    def test_log(self):
        data = formset(developer_comments='This is a test')
        o = ActivityLog.objects
        eq_(o.count(), 0)
        r = self.client.post(self.edit_url, data)
        self.assertNoFormErrors(r)
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_toggles(self):
        # Turn everything on.
        data = dict(developer_comments='Test comment!',
                    external_software='on',
                    site_specific='on',
                    view_source='on')

        r = self.client.post(self.edit_url, formset(**data))
        self.assertNoFormErrors(r)
        expected = dict(developer_comments='Test comment!',
                        external_software=True,
                        site_specific=True,
                        view_source=True)
        self.compare(expected)

        # And off.
        r = self.client.post(self.edit_url,
                             formset(developer_comments='Test comment!'))
        expected.update(external_software=False,
                        site_specific=False,
                        view_source=False)
        self.compare(expected)

    def test_devcomment_optional(self):
        data = dict(developer_comments='',
                    external_software='on',
                    site_specific='on',
                    view_source='on')
        r = self.client.post(self.edit_url, formset(**data))
        self.assertNoFormErrors(r)

        expected = dict(developer_comments='',
                        external_software=True,
                        site_specific=True,
                        view_source=True)
        self.compare(expected)


class TestAdmin(TestEdit):

    def setUp(self):
        super(TestAdmin, self).setUp()
        self.url = self.get_url('admin')
        self.edit_url = self.get_url('admin', edit=True)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def log_in_user(self):
        assert self.client.login(username=self.user.email, password='password')

    def log_in_with(self, rules):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Whatever', rules=rules)
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(username=user.email, password='password')


class TestAdminSettings(TestAdmin):

    def test_form_url(self):
        self.check_form_url('admin')

    def test_overview_visible_as_admin(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('form').length, 1)
        assert not r.context.get('form'), (
            'Admin Settings form should not be in context')

    def test_overview_forbidden_for_nonadmin(self):
        self.log_in_user()
        eq_(self.client.head(self.url).status_code, 403)

    def test_edit_get_as_admin(self):
        r = self.client.get(self.edit_url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('form').length, 1)
        assert r.context.get('form'), 'Admin Settings form expected in context'

    def test_edit_post_as_admin(self):
        # There are errors, but I don't care. I just want to see if I can POST.
        eq_(self.client.post(self.edit_url).status_code, 200)

    def test_edit_no_get_as_nonadmin(self):
        self.log_in_user()
        eq_(self.client.get(self.edit_url).status_code, 403)

    def test_edit_no_post_as_nonadmin(self):
        self.log_in_user()
        eq_(self.client.post(self.edit_url).status_code, 403)

    def post_contact(self, **kw):
        data = {'caption': 'ball so hard that ish cray',
                'position': '1',
                'upload_hash': 'abcdef',
                'mozilla_contact': 'a@mozilla.com'}
        data.update(kw)
        return self.client.post(self.edit_url, data)

    def test_mozilla_contact(self):
        self.post_contact()
        webapp = self.get_webapp()
        eq_(webapp.mozilla_contact, 'a@mozilla.com')

    def test_mozilla_contact_invalid(self):
        r = self.post_contact(
            mozilla_contact='<script>alert("xss")</script>@mozilla.com')
        webapp = self.get_webapp()
        self.assertFormError(r, 'form', 'mozilla_contact',
                             'Enter a valid e-mail address.')
        eq_(webapp.mozilla_contact, '')

    def test_staff(self):
        # Staff and Support Staff should have Apps:Configure.
        self.log_in_with('Apps:Configure')

        # Test GET.
        r = self.client.get(self.edit_url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('form').length, 1)
        assert r.context.get('form'), 'Admin Settings form expected in context'

        # Test POST. Ignore errors.
        eq_(self.client.post(self.edit_url).status_code, 200)

    def test_developer(self):
        # Developers have read-only on admin section.
        self.log_in_with('Apps:ViewConfiguration')

        # Test GET.
        r = self.client.get(self.edit_url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('form').length, 1)
        assert r.context.get('form'), 'Admin Settings form expected in context'

        # Test POST. Ignore errors.
        eq_(self.client.post(self.edit_url).status_code, 403)

    def test_ratings_edit_add(self):
        self.log_in_with('Apps:Configure')

        data = {'caption': 'ball so hard that ish cray',
                'position': '1',
                'upload_hash': 'abcdef',
                'app_ratings': '2'
                }
        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)
        webapp = self.get_webapp()
        eq_(list(webapp.content_ratings.values_list('ratings_body', 'rating')),
            [(0, 2)])

    def test_ratings_edit_update(self):
        self.log_in_with('Apps:Configure')
        webapp = self.get_webapp()
        ContentRating.objects.create(addon=webapp, ratings_body=0, rating=2)
        data = {'caption': 'ball so hard that ish cray',
                'position': '1',
                'upload_hash': 'abcdef',
                'app_ratings': ('1', '3')
                }
        r = self.client.post(self.edit_url, data)
        eq_(r.status_code, 200)
        eq_(list(webapp.content_ratings.all().values_list('ratings_body',
                                                          'rating')),
            [(0, 1), (0, 3)])
        #a second update doesn't duplicate existing ratings
        r = self.client.post(self.edit_url, data)
        eq_(list(webapp.content_ratings.all().values_list('ratings_body',
                                                          'rating')),
            [(0, 1), (0, 3)])
        del data['app_ratings']

        r = self.client.post(self.edit_url, data)
        assert not webapp.content_ratings.exists()


    def test_ratings_view(self):
        self.log_in_with('Apps:ViewConfiguration')
        webapp = self.get_webapp()
        ContentRating.objects.create(addon=webapp, ratings_body=0, rating=2)
        r = self.client.get(self.url)
        txt = pq(r.content)[0].xpath(
            "//label[@for='app_ratings']/../../td/div/text()")[0]
        eq_(txt,
            '%s - %s' % (RATINGS_BODIES[0].name,
                         RATINGS_BODIES[0].ratings[2].name))

    def test_set_flash(self):
        self.log_in_with('Apps:Configure')
        r = self.client.post(self.edit_url,
                         {'caption': 'x',
                          'position': '1',
                          'upload_hash': 'abcdef',
                          'flash': 'checked'})
        eq_(r.status_code, 200)
        assert self.webapp.uses_flash

    def test_unset_flash(self):
        self.webapp.versions.latest().files.latest().update(uses_flash=True)
        self.log_in_with('Apps:Configure')
        r = self.client.post(self.edit_url,
                         {'caption': 'x',
                          'position': '1',
                          'upload_hash': 'abcdef',
                          'flash': ''})
        eq_(r.status_code, 200)
        assert not self.webapp.uses_flash

    def test_flash_set_view(self):
        self.log_in_with('Apps:ViewConfiguration')
        self.webapp.versions.latest().files.latest().update(uses_flash=True)
        r = self.client.get(self.url)
        checkbox = pq(r.content)[0].xpath(
            "//label[@for='flash']/../../td/input")[0]
        eq_(checkbox.get('checked'), 'checked')

    def test_flash_unset_view(self):
        self.log_in_with('Apps:ViewConfiguration')
        r = self.client.get(self.url)
        checkbox = pq(r.content)[0].xpath(
            "//label[@for='flash']/../../td/input")[0]
        eq_(checkbox.get('checked'), None)


class TestPromoUpload(TestAdmin):

    def post(self, **kw):
        data = {'caption': 'ball so hard that ish cray',
                'position': '1',
                'upload_hash': 'abcdef'}
        data.update(kw)
        self.client.post(self.edit_url, data)

    def test_add(self):
        self.post()

        webapp = self.get_webapp()

        eq_(webapp.previews.count(), 1)
        eq_(list(webapp.get_previews()), [])

        promo = webapp.get_promo()
        eq_(promo.caption, '__promo__')
        eq_(promo.position, -1)

    def test_delete(self):
        self.post()
        assert self.get_webapp().get_promo()

        self.post(DELETE=True)
        assert not self.get_webapp().get_promo()
