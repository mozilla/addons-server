import json
import os
import tempfile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.db.models import Q
from django.test.utils import override_settings

import mock
from PIL import Image
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.helpers import user_media_path
from olympia.amo.tests import (
    addon_factory, formset, initial, req_factory_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.addons.forms import AddonFormBasic
from olympia.addons.models import (
    Addon, AddonCategory, AddonDependency, Category)
from olympia.bandwagon.models import (
    Collection, CollectionAddon, FeaturedCollection)
from olympia.devhub.models import ActivityLog
from olympia.devhub.views import edit_theme
from olympia.tags.models import Tag, AddonTag
from olympia.users.models import UserProfile


def get_section_url(addon, section, edit=False):
    args = [addon.slug, section]
    if edit:
        args.append('edit')
    return reverse('devhub.addons.section', args=args)


@override_settings(MEDIA_ROOT=None)  # Make it overridable.
class TestEdit(TestCase):
    fixtures = ['base/users', 'base/addon_3615',
                'base/addon_5579', 'base/addon_3615_categories']

    def setUp(self):
        # Make new for each test.
        settings.MEDIA_ROOT = tempfile.mkdtemp()
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

        self.tags = ['tag3', 'tag2', 'tag1']
        for t in self.tags:
            Tag(tag_text=t).save_tag(addon)

        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_url(self, section, edit=False):
        return get_section_url(self.addon, section, edit)

    def get_dict(self, **kw):
        fs = formset(self.cat_initial, initial_count=1)
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary',
                  'tags': ', '.join(self.tags)}
        result.update(**kw)
        result.update(fs)
        return result


class TestEditBasic(TestEdit):

    def setUp(self):
        super(TestEditBasic, self).setUp()
        self.basic_edit_url = self.get_url('basic', edit=True)
        ctx = self.client.get(self.basic_edit_url).context
        self.cat_initial = initial(ctx['cat_form'].initial_forms[0])

    def test_redirect(self):
        # /addon/:id => /addon/:id/edit
        r = self.client.get('/en-US/developers/addon/3615/', follow=True)
        self.assert3xx(r, self.url, 301)

    def test_edit(self):
        old_name = self.addon.name
        data = self.get_dict()

        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200
        addon = self.get_addon()

        assert unicode(addon.name) == data['name']
        assert addon.name.id == old_name.id

        assert unicode(addon.slug) == data['slug']
        assert unicode(addon.summary) == data['summary']

        assert [unicode(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_check_description(self):
        # Make sure bug 629779 doesn't return.
        old_desc = self.addon.description
        data = self.get_dict()

        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200
        addon = self.get_addon()

        assert addon.description == old_desc

    def test_edit_slug_invalid(self):
        old_edit = self.basic_edit_url
        data = self.get_dict(name='', slug='invalid')
        r = self.client.post(self.basic_edit_url, data)
        doc = pq(r.content)
        assert doc('form').attr('action') == old_edit

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
        assert r.status_code == 200

        # Fetch the page so the LinkifiedTranslation gets in cache.
        r = self.client.get(reverse('devhub.addons.edit', args=[data['slug']]))
        assert pq(r.content)('[data-name=summary]').html().strip() == (
            '<span lang="en-us">&lt;b&gt;oh my&lt;/b&gt;</span>')

        # Now make sure we don't have escaped content in the rendered form.
        form = AddonFormBasic(instance=self.get_addon(),
                              request=req_factory_factory('/'))
        html = pq('<body>%s</body>' % form['summary'])('[lang="en-us"]').html()
        assert html.strip() == '<b>oh my</b>'

    def test_edit_as_developer(self):
        self.login('regular@mozilla.com')
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        # Make sure we get errors when they are just regular users.
        assert r.status_code == 403

        devuser = UserProfile.objects.get(pk=999)
        self.get_addon().addonuser_set.create(
            user=devuser, role=amo.AUTHOR_ROLE_DEV)
        r = self.client.post(self.basic_edit_url, data)

        assert r.status_code == 200
        addon = self.get_addon()

        assert unicode(addon.name) == data['name']

        assert unicode(addon.slug) == data['slug']
        assert unicode(addon.summary) == data['summary']

        assert [unicode(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_name_required(self):
        data = self.get_dict(name='', slug='test_addon')
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_name_spaces(self):
        data = self.get_dict(name='    ', slug='test_addon')
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200
        self.assertFormError(
            r, 'form', 'slug',
            'This slug is already in use. Please choose another.')

    def test_edit_add_tag(self):
        count = ActivityLog.objects.all().count()
        self.tags.insert(0, 'tag4')
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        result = pq(r.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))
        html = ('<a href="/en-US/firefox/tag/tag4">tag4</a> added to '
                '<a href="/en-US/firefox/addon/test_slug/">new name</a>.')
        assert ActivityLog.objects.for_addons(self.addon).get(
            action=amo.LOG.ADD_TAG.id).to_string() == html
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADD_TAG.id).count() == count + 1

    def test_edit_blacklisted_tag(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        data = self.get_dict(tags='blue')
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        error = 'Invalid tag: blue'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_blacklisted_tags_2(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        Tag.objects.get_or_create(tag_text='darn', blacklisted=True)
        data = self.get_dict(tags='blue, darn, swearword')
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        error = 'Invalid tags: blue, darn'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_blacklisted_tags_3(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        Tag.objects.get_or_create(tag_text='darn', blacklisted=True)
        Tag.objects.get_or_create(tag_text='swearword', blacklisted=True)
        data = self.get_dict(tags='blue, darn, swearword')
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        error = 'Invalid tags: blue, darn, swearword'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_remove_tag(self):
        self.tags.remove('tag2')

        count = ActivityLog.objects.all().count()
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        result = pq(r.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))

        assert ActivityLog.objects.filter(
            action=amo.LOG.REMOVE_TAG.id).count() == count + 1

    def test_edit_minlength_tags(self):
        tags = self.tags
        tags.append('a' * (amo.MIN_TAG_LENGTH - 1))
        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        assert r.status_code == 200

        self.assertFormError(r, 'form', 'tags',
                             'All tags must be at least %d characters.' %
                             amo.MIN_TAG_LENGTH)

    def test_edit_max_tags(self):
        tags = self.tags

        for i in range(amo.MAX_TAGS + 1):
            tags.append('test%d' % i)

        data = self.get_dict()
        r = self.client.post(self.basic_edit_url, data)
        self.assertFormError(
            r, 'form', 'tags',
            'You have %d too many tags.' % (len(tags) - amo.MAX_TAGS))

    def test_edit_tag_empty_after_slug(self):
        start = Tag.objects.all().count()
        data = self.get_dict(tags='>>')
        self.client.post(self.basic_edit_url, data)

        # Check that the tag did not get created.
        assert start == Tag.objects.all().count()

    def test_edit_tag_slugified(self):
        data = self.get_dict(tags='<script>alert("foo")</script>')
        self.client.post(self.basic_edit_url, data)
        tag = Tag.objects.all().order_by('-pk')[0]
        assert tag.tag_text == 'scriptalertfooscript'

    def test_edit_categories_add(self):
        assert [c.id for c in self.get_addon().all_categories] == [22]
        self.cat_initial['categories'] = [22, 23]

        self.client.post(self.basic_edit_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22, 23]

    def _feature_addon(self, addon_id=3615):
        c = CollectionAddon.objects.create(
            addon_id=addon_id, collection=Collection.objects.create())
        FeaturedCollection.objects.create(collection=c.collection,
                                          application=amo.FIREFOX.id)
        cache.clear()

    def test_edit_categories_add_featured(self):
        """Ensure that categories cannot be changed for featured add-ons."""
        self._feature_addon()

        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)

        assert r.context['cat_form'].errors[0]['categories'] == (
            ['Categories cannot be changed while your add-on is featured for '
             'this application.'])
        # This add-on's categories should not change.
        assert sorted(addon_cats) == [22]

    def test_edit_categories_add_new_creatured_admin(self):
        """Ensure that admins can change categories for creatured add-ons."""
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self._feature_addon()
        r = self.client.get(self.basic_edit_url)
        doc = pq(r.content)
        assert doc('#addon-categories-edit div.addon-app-cats').length == 1
        assert doc('#addon-categories-edit > p').length == 0
        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert 'categories' not in r.context['cat_form'].errors[0]
        # This add-on's categories should change.
        assert sorted(addon_cats) == [22, 23]

    def test_edit_categories_disable_creatured(self):
        """Ensure that other forms are okay when disabling category changes."""
        self._feature_addon()
        self.cat_initial['categories'] = [22, 23]
        data = self.get_dict()
        self.client.post(self.basic_edit_url, data)
        assert unicode(self.get_addon().name) == data['name']

    def test_edit_categories_no_disclaimer(self):
        """Ensure that there is a not disclaimer for non-creatured add-ons."""
        r = self.client.get(self.basic_edit_url)
        doc = pq(r.content)
        assert doc('#addon-categories-edit div.addon-app-cats').length == 1
        assert doc('#addon-categories-edit > p').length == 0

    def test_edit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=23).save()
        assert [c.id for c in self.get_addon().all_categories] == [22, 23]

        self.cat_initial['categories'] = [22, 24]
        self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22, 24]

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
        assert [cat.id for cat in self.get_addon().all_categories] == [22, 23]

        self.cat_initial['categories'] = [22]
        self.client.post(self.basic_edit_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22]

    def test_edit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        assert r.context['cat_form'].errors[0]['categories'] == (
            ['This field is required.'])

    def test_edit_categories_max(self):
        assert amo.MAX_CATEGORIES == 2
        self.cat_initial['categories'] = [22, 23, 24]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        assert r.context['cat_form'].errors[0]['categories'] == (
            ['You can have only 2 categories.'])

    def test_edit_categories_other_failure(self):
        Category.objects.get(id=22).update(misc=True)
        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        assert r.context['cat_form'].errors[0]['categories'] == (
            ['The miscellaneous category cannot be combined with additional '
             'categories.'])

    def test_edit_categories_nonexistent(self):
        self.cat_initial['categories'] = [100]
        r = self.client.post(self.basic_edit_url, formset(self.cat_initial,
                                                          initial_count=1))
        assert r.context['cat_form'].errors[0]['categories'] == (
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

    def test_edit_restricted_tags(self):
        addon = self.get_addon()
        tag = Tag.objects.create(tag_text='restartless', restricted=True)
        AddonTag.objects.create(tag=tag, addon=addon)

        res = self.client.get(self.basic_edit_url)
        divs = pq(res.content)('#addon_tags_edit .edit-addon-details')
        assert len(divs) == 2
        assert 'restartless' in divs.eq(1).text()

    def test_text_not_none_when_has_flags(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#addon-flags').text() == 'This is a site-specific add-on.'

    def test_text_none_when_no_flags(self):
        addon = self.get_addon()
        addon.update(external_software=False, site_specific=False)
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#addon-flags').text() == 'None'

    def test_nav_links(self):
        activity_url = reverse('devhub.feed', args=['a3615'])
        r = self.client.get(self.url)
        doc = pq(r.content)('#edit-addon-nav')
        assert doc('ul:last').find('li a').eq(1).attr('href') == (
            activity_url)
        assert doc('.view-stats').length == 1

    def get_l10n_urls(self):
        paths = ('devhub.addons.edit', 'devhub.addons.profile',
                 'devhub.addons.owner')
        return [reverse(p, args=['a3615']) for p in paths]

    def test_l10n(self):
        Addon.objects.get(id=3615).update(default_locale='en-US')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            assert pq(r.content)('#l10n-menu').attr('data-default') == 'en-us'

    def test_l10n_not_us(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            assert pq(r.content)('#l10n-menu').attr('data-default') == 'fr'

    def test_l10n_not_us_id_url(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            url = '/id' + url[6:]
            r = self.client.get(url)
            assert pq(r.content)('#l10n-menu').attr('data-default') == 'fr'


class TestEditMedia(TestEdit):

    def setUp(self):
        super(TestEditMedia, self).setUp()
        self.media_edit_url = self.get_url('media', True)
        self.icon_upload = reverse('devhub.addons.upload_icon',
                                   args=[self.addon.slug])
        self.preview_upload = reverse('devhub.addons.upload_preview',
                                      args=[self.addon.slug])

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

    def test_icon_upload_attributes(self):
        doc = pq(self.client.get(self.media_edit_url).content)
        field = doc('input[name=icon_upload]')
        assert field.length == 1
        assert sorted(field.attr('data-allowed-types').split('|')) == (
            ['image/jpeg', 'image/png'])
        assert field.attr('data-upload-url') == self.icon_upload

    def test_edit_media_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_media_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.media_edit_url, data_formset)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/appearance-64.png')

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

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
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        url = addon.get_icon_url(64)
        assert ('addon_icons/3/%s' % addon.id) in url, (
            'Unexpected path: %r' % url)

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(user_media_path('addon_icons'),
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert storage.exists(dest)

        assert Image.open(storage.open(dest)).size == (32, 12)

    def test_edit_media_icon_log(self):
        self.test_edit_media_uploadedicon()
        log = ActivityLog.objects.all()
        assert log.count() == 1
        assert log[0].action == amo.LOG.CHANGE_ICON.id

    def test_edit_media_uploadedicon_noresize(self):
        img = "static/img/notifications/error.png"
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
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        addon_url = addon.get_icon_url(64).split('?')[0]
        assert addon_url.endswith('addon_icons/3/%s-64.png' % addon.id), (
            'Unexpected path: %r' % addon_url)

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(user_media_path('addon_icons'),
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert storage.exists(dest)

        assert Image.open(storage.open(dest)).size == (48, 48)

    def check_image_type(self, url, msg):
        img = 'static/js/zamboni/devhub.js'
        src_image = open(img, 'rb')

        res = self.client.post(url, {'upload_image': src_image})
        response_json = json.loads(res.content)
        assert response_json['errors'][0] == msg

    def test_edit_media_icon_wrong_type(self):
        self.check_image_type(self.icon_upload,
                              'Icons must be either PNG or JPG.')

    def test_edit_media_screenshot_wrong_type(self):
        self.check_image_type(self.preview_upload,
                              'Images must be either PNG or JPG.')

    def setup_image_status(self):
        addon = self.get_addon()
        self.icon_dest = os.path.join(addon.get_icon_dir(),
                                      '%s-32.png' % addon.id)
        os.makedirs(os.path.dirname(self.icon_dest))
        with storage.open(self.icon_dest, 'w') as f:
            f.write('some icon data\n')

        self.preview = addon.previews.create()
        self.preview.save()
        os.makedirs(os.path.dirname(self.preview.thumbnail_path))
        with storage.open(self.preview.thumbnail_path, 'w') as f:
            f.write('some icon data\n')
        self.url = reverse('devhub.ajax.image.status', args=[addon.slug])

    def test_image_status_no_choice(self):
        addon = self.get_addon()
        addon.update(icon_type='')
        url = reverse('devhub.ajax.image.status', args=[addon.slug])
        result = json.loads(self.client.get(url).content)
        assert result['icons']

    def test_image_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_fails(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
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
        storage.delete(self.preview.thumbnail_path)
        result = json.loads(self.client.get(self.url).content)
        assert not result['previews']

    def test_image_status_persona(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        self.get_addon().update(type=amo.ADDON_PERSONA)
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_default(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        self.get_addon().update(icon_type='icon/photos')
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def check_image_animated(self, url, msg):
        filehandle = open(get_image_path('animated.png'), 'rb')

        res = self.client.post(url, {'upload_image': filehandle})
        response_json = json.loads(res.content)
        assert response_json['errors'][0] == msg

    def test_icon_animated(self):
        self.check_image_animated(self.icon_upload,
                                  'Icons cannot be animated.')

    def test_screenshot_animated(self):
        self.check_image_animated(self.preview_upload,
                                  'Images cannot be animated.')

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

        assert str(self.get_addon().previews.all()[0].caption) == 'hi'

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

        assert str(self.get_addon().previews.all()[0].caption) == 'bye'
        assert len(self.get_addon().previews.all()) == 1

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
        assert data_formset['files-0-caption'] == 'third'
        assert data_formset['files-1-caption'] == 'second'
        assert data_formset['files-2-caption'] == 'first'

        self.client.post(self.media_edit_url, data_formset)
        # They should come out "first", "second", "third"
        assert str(self.get_addon().previews.all()[0].caption) == 'first'
        assert str(self.get_addon().previews.all()[1].caption) == 'second'
        assert str(self.get_addon().previews.all()[2].caption) == 'third'

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

        assert len(self.get_addon().previews.all()) == 0

    def test_edit_media_preview_add_another(self):
        self.preview_add()
        self.preview_add()

        assert len(self.get_addon().previews.all()) == 2

    def test_edit_media_preview_add_two(self):
        self.preview_add(2)

        assert len(self.get_addon().previews.all()) == 2


class TestEditDetails(TestEdit):

    def setUp(self):
        super(TestEditDetails, self).setUp()
        self.details_url = self.get_url('details')
        self.details_edit_url = self.get_url('details', edit=True)

    def test_edit(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US',
                    homepage='http://twitter.com/fligtarsmom')

        r = self.client.post(self.details_edit_url, data)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

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
        assert doc('#edit-addon-details span[lang]').html() == (
            "This<br/><b>IS</b>&lt;script&gt;alert('awesome')&lt;/script&gt;")

    def test_edit_homepage_optional(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US', homepage='')

        r = self.client.post(self.details_edit_url, data)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        description, homepage = map(unicode, [self.addon.description,
                                              self.addon.homepage])
        # TODO: description should get fixed up with the form.
        error = ('Before changing your default locale you must have a name, '
                 'summary, and description in that locale. '
                 'You are missing ')

        d = dict(description=description, homepage=homepage,
                 default_locale='fr')
        r = self.client.post(self.details_edit_url, d)
        # We can't use assertFormError here, because the missing fields are
        # stored in a dict, which isn't ordered.
        form_error = r.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'name'" in form_error
        assert "'summary'" in form_error

        # Now we have a name.
        self.addon.name = {'fr': 'fr name'}
        self.addon.save()
        r = self.client.post(self.details_edit_url, d)
        form_error = r.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'summary'" in form_error

        # Now we have a summary.
        self.addon.summary = {'fr': 'fr summary'}
        self.addon.save()
        r = self.client.post(self.details_edit_url, d)
        form_error = r.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error

        # Now we're sending an fr description with the form.
        d['description_fr'] = 'fr description'
        r = self.client.post(self.details_edit_url, d)
        assert r.context['form'].errors == {}

    def test_edit_default_locale_frontend_error(self):
        d = dict(description='xx', homepage='https://staticfil.es/',
                 default_locale='fr')
        r = self.client.post(self.details_edit_url, d)
        self.assertContains(r, 'Before changing your default locale you must')

    def test_edit_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')
        r = self.client.get(self.details_url)
        assert pq(r.content)('.addon_edit_locale').eq(0).text() == (
            'English (US)')


class TestEditSupport(TestEdit):

    def setUp(self):
        super(TestEditSupport, self).setUp()
        self.support_url = self.get_url('support')
        self.support_edit_url = self.get_url('support', edit=True)

    def test_edit_support(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='http://apple.com/')

        r = self.client.post(self.support_edit_url, data)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_support_optional_url(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='')

        r = self.client.post(self.support_edit_url, data)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_support_optional_email(self):
        data = dict(support_email='',
                    support_url='http://apple.com/')

        r = self.client.post(self.support_edit_url, data)
        assert r.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]


class TestEditTechnical(TestEdit):
    fixtures = TestEdit.fixtures + ['addons/persona', 'base/addon_40',
                                    'base/addon_1833_yoono',
                                    'base/addon_4664_twitterbar.json',
                                    'base/addon_5299_gcal', 'base/addon_6113']

    def setUp(self):
        super(TestEditTechnical, self).setUp()
        self.dependent_addon = Addon.objects.get(id=5579)
        AddonDependency.objects.create(addon=self.addon,
                                       dependent_addon=self.dependent_addon)
        self.technical_url = self.get_url('technical')
        self.technical_edit_url = self.get_url('technical', edit=True)
        ctx = self.client.get(self.technical_edit_url).context
        self.dep = initial(ctx['dependency_form'].initial_forms[0])
        self.dep_initial = formset(self.dep, prefix='dependencies',
                                   initial_count=1)

    def dep_formset(self, *args, **kw):
        kw.setdefault('initial_count', 1)
        kw.setdefault('prefix', 'dependencies')
        return formset(self.dep, *args, **kw)

    def formset(self, data):
        return self.dep_formset(**data)

    def test_log(self):
        data = self.formset({'developer_comments': 'This is a test'})
        o = ActivityLog.objects
        assert o.count() == 0
        r = self.client.post(self.technical_edit_url, data)
        assert r.context['form'].errors == {}
        assert o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count() == 1

    def test_technical_on(self):
        # Turn everything on
        data = dict(developer_comments='Test comment!',
                    external_software='on',
                    site_specific='on',
                    view_source='on',
                    whiteboard='Whiteboard info.')

        r = self.client.post(self.technical_edit_url, self.formset(data))
        assert r.context['form'].errors == {}

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                assert unicode(getattr(addon, k)) == unicode(data[k])
            elif k == 'whiteboard':
                assert unicode(getattr(addon, k)) == unicode(data[k])
            else:
                assert getattr(addon, k) == (data[k] == 'on')

        # Andddd offf
        data = dict(developer_comments='Test comment!')
        r = self.client.post(self.technical_edit_url, self.formset(data))
        addon = self.get_addon()

        assert not addon.external_software
        assert not addon.site_specific
        assert not addon.view_source

    def test_technical_devcomment_notrequired(self):
        data = dict(developer_comments='',
                    external_software='on',
                    site_specific='on',
                    view_source='on')
        r = self.client.post(self.technical_edit_url, self.formset(data))
        assert r.context['form'].errors == {}

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                assert unicode(getattr(addon, k)) == unicode(data[k])
            else:
                assert getattr(addon, k) == (data[k] == 'on')

    def test_auto_repackage_not_shown(self):
        f = self.addon.current_version.all_files[0]
        f.jetpack_version = None
        f.save()
        r = self.client.get(self.technical_edit_url)
        self.assertNotContains(r, 'Upgrade SDK?')

    def test_auto_repackage_shown(self):
        f = self.addon.current_version.all_files[0]
        f.jetpack_version = '1.0'
        f.save()
        r = self.client.get(self.technical_edit_url)
        self.assertContains(r, 'Upgrade SDK?')

    def test_dependencies_none(self):
        AddonDependency.objects.all().delete()
        assert list(self.addon.all_dependencies) == []
        r = self.client.get(self.technical_url)
        assert pq(r.content)('#required-addons .empty').length == 1

    def test_dependencies_overview(self):
        assert [d.id for d in self.addon.all_dependencies] == [5579]
        r = self.client.get(self.technical_url)
        req = pq(r.content)('#required-addons')
        assert req.length == 1
        assert req.attr('data-src') == (
            reverse('devhub.ajax.dependencies', args=[self.addon.slug]))
        assert req.find('li').length == 1
        a = req.find('a')
        assert a.attr('href') == self.dependent_addon.get_url_path()
        assert a.text() == unicode(self.dependent_addon.name)

    def test_dependencies_initial(self):
        r = self.client.get(self.technical_edit_url)
        form = pq(r.content)('#required-addons .dependencies li[data-addonid]')
        assert form.length == 1
        assert form.find('input[id$=-dependent_addon]').val() == (
            str(self.dependent_addon.id))
        div = form.find('div')
        assert div.attr('style') == (
            'background-image:url(%s)' % self.dependent_addon.icon_url)
        a = div.find('a')
        assert a.attr('href') == self.dependent_addon.get_url_path()
        assert a.text() == unicode(self.dependent_addon.name)

    def test_dependencies_add(self):
        addon = Addon.objects.get(id=5299)
        assert addon.type == amo.ADDON_EXTENSION
        assert addon in list(Addon.objects.reviewed())

        d = self.dep_formset({'dependent_addon': addon.id})
        r = self.client.post(self.technical_edit_url, d)
        assert not any(r.context['dependency_form'].errors)
        self.check_dep_ids([self.dependent_addon.id, addon.id])

        r = self.client.get(self.technical_edit_url)
        reqs = pq(r.content)('#required-addons .dependencies')
        assert reqs.find('li[data-addonid]').length == 2
        req = reqs.find('li[data-addonid="5299"]')
        assert req.length == 1
        a = req.find('div a')
        assert a.attr('href') == addon.get_url_path()
        assert a.text() == unicode(addon.name)

    def test_dependencies_limit(self):
        deps = Addon.objects.reviewed().exclude(
            Q(id__in=[self.addon.id, self.dependent_addon.id]) |
            Q(type=amo.ADDON_PERSONA))
        args = []
        assert deps.count() > 3  # The limit is 3.
        for dep in deps:
            args.append({'dependent_addon': dep.id})
        d = self.dep_formset(*args)
        r = self.client.post(self.technical_edit_url, d)
        assert r.context['dependency_form'].non_form_errors() == (
            ['There cannot be more than 3 required add-ons.'])

    def test_dependencies_limit_with_deleted_form(self):
        deps = Addon.objects.reviewed().exclude(
            Q(id__in=[self.addon.id, self.dependent_addon.id]) |
            Q(type=amo.ADDON_PERSONA))[:3]
        args = []
        for dep in deps:
            args.append({'dependent_addon': dep.id})

        # If we delete one form and add three, everything should be A-OK.
        self.dep['DELETE'] = True
        d = self.dep_formset(*args)
        r = self.client.post(self.technical_edit_url, d)
        assert not any(r.context['dependency_form'].errors)
        self.check_dep_ids(deps.values_list('id', flat=True))

    def check_dep_ids(self, expected=[]):
        a = AddonDependency.objects.values_list('dependent_addon__id',
                                                flat=True)
        assert sorted(list(a)) == sorted(expected)

    def check_bad_dep(self, r):
        """This helper checks that bad dependency data doesn't go through."""
        assert r.context['dependency_form'].errors[1]['dependent_addon'] == (
            ['Select a valid choice. That choice is not one of the available '
             'choices.'])
        self.check_dep_ids([self.dependent_addon.id])

    def test_dependencies_add_reviewed(self):
        """Ensure that reviewed add-ons can be made as dependencies."""
        addon = Addon.objects.get(id=40)
        for status in amo.REVIEWED_STATUSES:
            addon.update(status=status)

            assert addon in list(Addon.objects.reviewed())
            d = self.dep_formset({'dependent_addon': addon.id})
            r = self.client.post(self.technical_edit_url, d)
            assert not any(r.context['dependency_form'].errors)
            self.check_dep_ids([self.dependent_addon.id, addon.id])

            AddonDependency.objects.get(dependent_addon=addon).delete()

    def test_dependencies_no_add_unreviewed(self):
        """Ensure that unreviewed add-ons cannot be made as dependencies."""
        addon = Addon.objects.get(id=40)
        for status in amo.UNREVIEWED_STATUSES:
            addon.update(status=status)

            assert addon not in list(Addon.objects.reviewed())
            d = self.dep_formset({'dependent_addon': addon.id})
            r = self.client.post(self.technical_edit_url, d)
            self.check_bad_dep(r)

    def test_dependencies_no_add_reviewed_persona(self):
        """Ensure that reviewed Personas cannot be made as dependencies."""
        addon = Addon.objects.get(id=15663)
        assert addon.type == amo.ADDON_PERSONA
        assert addon in list(Addon.objects.reviewed())
        d = self.dep_formset({'dependent_addon': addon.id})
        r = self.client.post(self.technical_edit_url, d)
        self.check_bad_dep(r)

    def test_dependencies_no_add_unreviewed_persona(self):
        """Ensure that unreviewed Personas cannot be made as dependencies."""
        addon = Addon.objects.get(id=15663)
        addon.update(status=amo.STATUS_UNREVIEWED)
        assert addon.status == amo.STATUS_UNREVIEWED
        assert addon not in list(Addon.objects.reviewed())
        d = self.dep_formset({'dependent_addon': addon.id})
        r = self.client.post(self.technical_edit_url, d)
        self.check_bad_dep(r)

    def test_dependencies_add_self(self):
        """Ensure that an add-on cannot be made dependent on itself."""
        d = self.dep_formset({'dependent_addon': self.addon.id})
        r = self.client.post(self.technical_edit_url, d)
        self.check_bad_dep(r)

    def test_dependencies_add_invalid(self):
        """Ensure that a non-existent add-on cannot be a dependency."""
        d = self.dep_formset({'dependent_addon': 9999})
        r = self.client.post(self.technical_edit_url, d)
        self.check_bad_dep(r)

    def test_dependencies_add_duplicate(self):
        """Ensure that an add-on cannot be made dependent more than once."""
        d = self.dep_formset({'dependent_addon': self.dependent_addon.id})
        r = self.client.post(self.technical_edit_url, d)
        assert r.context['dependency_form'].forms[1].non_field_errors() == (
            ['Addon dependency with this Addon and Dependent addon already '
             'exists.'])
        self.check_dep_ids([self.dependent_addon.id])

    def test_dependencies_delete(self):
        self.dep['DELETE'] = True
        d = self.dep_formset(total_count=1, initial_count=1)
        r = self.client.post(self.technical_edit_url, d)
        assert not any(r.context['dependency_form'].errors)
        self.check_dep_ids()

    def test_dependencies_add_delete(self):
        """Ensure that we can both delete a dependency and add another."""
        self.dep['DELETE'] = True
        d = self.dep_formset({'dependent_addon': 5299})
        r = self.client.post(self.technical_edit_url, d)
        assert not any(r.context['dependency_form'].errors)
        self.check_dep_ids([5299])


class TestAdmin(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def login_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def login_user(self):
        assert self.client.login(username='del@icio.us', password='password')

    def test_show_admin_settings_admin(self):
        self.login_admin()
        url = reverse('devhub.addons.edit', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 200
        self.assertContains(r, 'Admin Settings')
        assert 'admin_form' in r.context, 'AdminForm expected in context.'

    def test_show_admin_settings_nonadmin(self):
        self.login_user()
        url = reverse('devhub.addons.edit', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 200
        self.assertNotContains(r, 'Admin Settings')
        assert 'admin_form' not in r.context, (
            'AdminForm not expected in context.')

    def test_post_as_admin(self):
        self.login_admin()
        url = reverse('devhub.addons.admin', args=['a3615'])
        r = self.client.post(url)
        assert r.status_code == 200

    def test_post_as_nonadmin(self):
        self.login_user()
        url = reverse('devhub.addons.admin', args=['a3615'])
        r = self.client.post(url)
        assert r.status_code == 403


class TestThemeEdit(TestCase):
    fixtures = ['base/user_999']

    def setUp(self):
        super(TestThemeEdit, self).setUp()
        self.addon = addon_factory(type=amo.ADDON_PERSONA)
        self.user = UserProfile.objects.get()
        self.addon.addonuser_set.create(user=self.user)

    @mock.patch('olympia.amo.messages.error')
    def test_desc_too_long_error(self, message_mock):
        data = {'description': 'a' * 501}
        req = req_factory_factory(
            self.addon.get_dev_url('edit'),
            user=self.user, post=True, data=data, session={})
        r = edit_theme(req, self.addon.slug, self.addon)
        doc = pq(r.content)
        assert 'characters' in doc('#trans-description + ul li').text()

    def test_no_reupload_on_pending(self):
        self.addon.update(status=amo.STATUS_PENDING)
        req = req_factory_factory(
            self.addon.get_dev_url('edit'), user=self.user, session={})
        r = edit_theme(req, self.addon.slug, self.addon)
        doc = pq(r.content)
        assert not doc('a.reupload')

        self.addon.update(status=amo.STATUS_PUBLIC)
        req = req_factory_factory(
            self.addon.get_dev_url('edit'), user=self.user, session={})
        r = edit_theme(req, self.addon.slug, self.addon)
        doc = pq(r.content)
        assert doc('a.reupload')

    def test_color_input_is_empty_at_creation(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('devhub.themes.submit'))
        doc = pq(r.content)
        el = doc('input.color-picker')
        assert el.attr('type') == 'text'
        assert not el.attr('value')

    def test_color_input_is_not_empty_at_edit(self):
        color = "123456"
        self.addon.persona.accentcolor = color
        self.addon.persona.save()
        self.client.login(username='regular@mozilla.com', password='password')
        url = reverse('devhub.themes.edit', args=(self.addon.slug, ))
        r = self.client.get(url)
        doc = pq(r.content)
        el = doc('input#id_accentcolor')
        assert el.attr('type') == 'text'
        assert el.attr('value') == "#" + color
