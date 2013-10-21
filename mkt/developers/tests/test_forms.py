import json
import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files.uploadedfile import SimpleUploadedFile

import mock
from nose.tools import eq_
from test_utils import RequestFactory

import amo
import amo.tests
from amo.tests import app_factory, version_factory
from amo.tests.test_helpers import get_image_path
from addons.models import Addon, AddonCategory, Category
from files.helpers import copyfileobj
from tags.models import Tag
from users.models import UserProfile

import mkt
from mkt.developers import forms
from mkt.developers.tests.test_views_edit import TestAdmin
from mkt.site.fixtures import fixture
from mkt.webapps.models import (AddonExcludedRegion as AER, ContentRating,
                                Webapp)


class TestPreviewForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.dest = os.path.join(settings.TMP_PATH, 'preview')
        if not os.path.exists(self.dest):
            os.makedirs(self.dest)

    @mock.patch('amo.models.ModelBase.update')
    def test_preview_modified(self, update_mock):
        name = 'transparent.png'
        form = forms.PreviewForm({'upload_hash': name,
                                  'position': 1})
        shutil.copyfile(get_image_path(name), os.path.join(self.dest, name))
        assert form.is_valid(), form.errors
        form.save(self.addon)
        assert update_mock.called

    def test_preview_size(self):
        name = 'non-animated.gif'
        form = forms.PreviewForm({'upload_hash': name,
                                  'position': 1})
        with storage.open(os.path.join(self.dest, name), 'wb') as f:
            copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid(), form.errors
        form.save(self.addon)
        eq_(self.addon.previews.all()[0].sizes,
            {u'image': [250, 297], u'thumbnail': [180, 214]})

    def check_file_type(self, type_):
        form = forms.PreviewForm({'upload_hash': type_,
                                  'position': 1})
        assert form.is_valid(), form.errors
        form.save(self.addon)
        return self.addon.previews.all()[0].filetype

    @mock.patch('lib.video.tasks.resize_video')
    def test_preview_good_file_type(self, resize_video):
        eq_(self.check_file_type('x.video-webm'), 'video/webm')

    def test_preview_other_file_type(self):
        eq_(self.check_file_type('x'), 'image/png')

    def test_preview_bad_file_type(self):
        eq_(self.check_file_type('x.foo'), 'image/png')


class TestCategoryForm(amo.tests.WebappTestCase):
    fixtures = fixture('user_999', 'webapp_337141')

    def setUp(self):
        super(TestCategoryForm, self).setUp()
        self.user = UserProfile.objects.get(username='regularuser')
        self.app = Webapp.objects.get(pk=337141)
        self.request = RequestFactory()
        self.request.user = self.user
        self.request.groups = ()

        self.cat = Category.objects.create(type=amo.ADDON_WEBAPP)

    def _make_form(self, data=None):
        self.form = forms.CategoryForm(
            data, product=self.app, request=self.request)

    def _cat_count(self):
        return self.form.fields['categories'].queryset.count()

    def test_has_no_cats(self):
        self._make_form()
        eq_(self._cat_count(), 1)
        eq_(self.form.max_categories(), 2)

    def test_save_cats(self):
        self._make_form({'categories':
            map(str, Category.objects.filter(type=amo.ADDON_WEBAPP)
                                     .values_list('id', flat=True))})
        assert self.form.is_valid(), self.form.errors
        self.form.save()
        eq_(AddonCategory.objects.filter(addon=self.app).count(),
            Category.objects.count())
        eq_(self.form.max_categories(), 2)


class TestRegionForm(amo.tests.WebappTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        super(TestRegionForm, self).setUp()
        self.request = RequestFactory()
        self.kwargs = {'product': self.app}

    def test_initial_empty(self):
        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], mkt.regions.ALL_REGION_IDS)
        eq_(form.initial['enable_new_regions'], False)

    def test_initial_excluded_in_region(self):
        AER.objects.create(addon=self.app, region=mkt.regions.BR.id)

        regions = list(mkt.regions.ALL_REGION_IDS)
        regions.remove(mkt.regions.BR.id)

        eq_(self.get_app().get_region_ids(worldwide=True), regions)

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], regions)
        eq_(form.initial['enable_new_regions'], False)

    def test_initial_excluded_in_regions_and_future_regions(self):
        regions = [mkt.regions.BR, mkt.regions.UK, mkt.regions.WORLDWIDE]
        for region in regions:
            AER.objects.create(addon=self.app, region=region.id)

        regions = list(mkt.regions.ALL_REGION_IDS)
        regions.remove(mkt.regions.BR.id)
        regions.remove(mkt.regions.UK.id)
        regions.remove(mkt.regions.WORLDWIDE.id)

        eq_(self.get_app().get_region_ids(), regions)

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], regions)
        eq_(form.initial['enable_new_regions'], False)

    def test_worldwide_only(self):
        form = forms.RegionForm(data={'regions': [mkt.regions.WORLDWIDE.id]},
                                **self.kwargs)
        assert form.is_valid(), form.errors

    def test_enable_new_regions(self):
        form = forms.RegionForm(data={'enable_new_regions': 'on',
                                      'regions': mkt.regions.ALL_REGION_IDS},
                                **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.enable_new_regions, True)

    def test_no_regions(self):
        form = forms.RegionForm(data={}, **self.kwargs)
        assert not form.is_valid()
        eq_(form.errors,
            {'__all__': ['You must select at least one region.']})

    def test_exclude_each_region(self):
        """Test that it's possible to exclude each region."""

        for region_id in mkt.regions.ALL_REGION_IDS:
            to_exclude = list(mkt.regions.ALL_REGION_IDS)
            to_exclude.remove(region_id)

            form = forms.RegionForm(
                data={'regions': to_exclude,
                      'enable_new_regions': 'on'}, **self.kwargs)
            assert form.is_valid(), form.errors
            form.save()

            eq_(self.app.get_region_ids(True), to_exclude)

    def test_unrated_games_excluded(self):
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm({'regions': mkt.regions.REGION_IDS,
                                 'enable_new_regions': True}, **self.kwargs)

        # Developers should still be able to save form OK, even
        # if they pass a bad region. Think of the grandfathered developers.
        assert form.is_valid(), form.errors
        form.save()

        # No matter what the developer tells us, still exclude Brazilian
        # and German games.
        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(set(form.initial['regions']),
            set(mkt.regions.REGION_IDS) -
            set([mkt.regions.BR.id, mkt.regions.DE.id,
                 mkt.regions.WORLDWIDE.id]))
        eq_(form.initial['enable_new_regions'], True)

    def test_unrated_games_already_excluded(self):
        regions = [x.id for x in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS]
        for region in regions:
            AER.objects.create(addon=self.app, region=region)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm({'regions': mkt.regions.REGION_IDS,
                                 'enable_new_regions': True}, **self.kwargs)

        assert form.is_valid()
        form.save()

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(set(form.initial['regions']),
            set(mkt.regions.REGION_IDS) -
            set(regions + [mkt.regions.WORLDWIDE.id]))
        eq_(form.initial['enable_new_regions'], True)

    def test_rated_games_with_content_rating(self):
        # This game has a government content rating!
        for region in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS:
            rb = region.ratingsbodies[0]
            ContentRating.objects.create(
                addon=self.app, ratings_body=rb.id, rating=rb.ratings[0].id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm({'regions': mkt.regions.ALL_REGION_IDS,
                                 'enable_new_regions': 'on'}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)

    def test_exclude_worldwide(self):
        form = forms.RegionForm({'regions': mkt.regions.REGION_IDS,
                                 'enable_new_regions': False}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.REGION_IDS)

    def test_reinclude_region(self):
        AER.objects.create(addon=self.app, region=mkt.regions.BR.id)

        form = forms.RegionForm({'regions': mkt.regions.ALL_REGION_IDS,
                                 'enable_new_regions': True}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)

    def test_reinclude_worldwide(self):
        AER.objects.create(addon=self.app, region=mkt.regions.WORLDWIDE.id)

        form = forms.RegionForm({'regions': mkt.regions.ALL_REGION_IDS},
                                **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)

    def test_worldwide_valid_choice_paid(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        form = forms.RegionForm(
            {'regions': [mkt.regions.WORLDWIDE.id]}, **self.kwargs)
        assert form.is_valid(), form.errors

    def test_worldwide_valid_choice_free(self):
        form = forms.RegionForm(
            {'regions': [mkt.regions.WORLDWIDE.id]}, **self.kwargs)
        assert form.is_valid(), form.errors


class TestNewManifestForm(amo.tests.TestCase):

    @mock.patch('mkt.developers.forms.verify_app_domain')
    def test_normal_validator(self, _verify_app_domain):
        form = forms.NewManifestForm({'manifest': 'http://omg.org/yes.webapp'},
            is_standalone=False)
        assert form.is_valid()
        assert _verify_app_domain.called

    @mock.patch('mkt.developers.forms.verify_app_domain')
    def test_standalone_validator(self, _verify_app_domain):
        form = forms.NewManifestForm({'manifest': 'http://omg.org/yes.webapp'},
            is_standalone=True)
        assert form.is_valid()
        assert not _verify_app_domain.called


class TestPackagedAppForm(amo.tests.AMOPaths, amo.tests.WebappTestCase):

    def setUp(self):
        super(TestPackagedAppForm, self).setUp()
        path = self.packaged_app_path('mozball.zip')
        self.files = {'upload': SimpleUploadedFile('mozball.zip',
                                                   open(path).read())}

    def test_not_there(self):
        form = forms.NewPackagedAppForm({}, {})
        assert not form.is_valid()
        eq_(form.errors['upload'], [u'This field is required.'])
        eq_(form.file_upload, None)

    def test_right_size(self):
        form = forms.NewPackagedAppForm({}, self.files)
        assert form.is_valid(), form.errors
        assert form.file_upload

    def test_too_big(self):
        form = forms.NewPackagedAppForm({}, self.files, max_size=5)
        assert not form.is_valid()
        validation = json.loads(form.file_upload.validation)
        assert 'messages' in validation, 'No messages in validation.'
        eq_(validation['messages'][0]['message'],
            u'Packaged app too large for submission. Packages must be less '
            u'than 5 bytes.')

    def test_origin_exists(self):
        self.app.update(app_domain='app://hy.fr')
        form = forms.NewPackagedAppForm({}, self.files)
        assert not form.is_valid()
        validation = json.loads(form.file_upload.validation)
        eq_(validation['messages'][0]['message'],
            'An app already exists on this domain; only one app per domain is '
            'allowed.')


class TestTransactionFilterForm(amo.tests.TestCase):

    def setUp(self):
        (app_factory(), app_factory())
        # Need queryset to initialize form.
        self.apps = Webapp.objects.all()
        self.data = {
            'app': self.apps[0].id,
            'transaction_type': 1,
            'transaction_id': 1,
            'date_from_day': '1',
            'date_from_month': '1',
            'date_from_year': '2012',
            'date_to_day': '1',
            'date_to_month': '1',
            'date_to_year': '2013',
        }

    def test_basic(self):
        """Test the form doesn't crap out."""
        form = forms.TransactionFilterForm(self.data, apps=self.apps)
        assert form.is_valid(), form.errors

    def test_app_choices(self):
        """Test app choices."""
        form = forms.TransactionFilterForm(self.data, apps=self.apps)
        for app in self.apps:
            assertion = (app.id, app.name) in form.fields['app'].choices
            assert assertion, '(%s, %s) not in choices' % (app.id, app.name)


class TestAppFormBasic(amo.tests.TestCase):

    def setUp(self):
        self.data = {
            'slug': 'yolo',
            'manifest_url': 'https://omg.org/yes.webapp',
            'description': 'You Only Live Once'
        }
        self.request = mock.Mock()
        self.request.groups = ()

    def post(self):
        self.form = forms.AppFormBasic(
            self.data, instance=Webapp.objects.create(app_slug='yolo'),
            request=self.request)

    def test_success(self):
        self.post()
        eq_(self.form.is_valid(), True, self.form.errors)
        eq_(self.form.errors, {})

    def test_slug_invalid(self):
        Webapp.objects.create(app_slug='yolo')
        self.post()
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors,
            {'slug': ['This slug is already in use. Please choose another.']})


class TestAppVersionForm(amo.tests.TestCase):

    def setUp(self):
        self.request = mock.Mock()
        self.app = app_factory(make_public=amo.PUBLIC_IMMEDIATELY,
                               version_kw={'version': '1.0',
                                           'created': self.days_ago(5)})
        version_factory(addon=self.app, version='2.0',
                        file_kw=dict(status=amo.STATUS_PENDING))
        self.app.reload()

    def get_form(self, version, data=None):
        return forms.AppVersionForm(data, instance=version)

    def test_get_publish(self):
        form = self.get_form(self.app.latest_version)
        eq_(form.fields['publish_immediately'].initial, True)

        self.app.update(make_public=amo.PUBLIC_WAIT)
        self.app.reload()
        form = self.get_form(self.app.latest_version)
        eq_(form.fields['publish_immediately'].initial, False)

    def test_post_publish(self):
        # Using the latest_version, which is pending.
        form = self.get_form(self.app.latest_version,
                             data={'publish_immediately': True})
        eq_(form.is_valid(), True)
        form.save()
        self.app.reload()
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)

        form = self.get_form(self.app.latest_version,
                             data={'publish_immediately': False})
        eq_(form.is_valid(), True)
        form.save()
        self.app.reload()
        eq_(self.app.make_public, amo.PUBLIC_WAIT)

    def test_post_publish_not_pending(self):
        # Using the current_version, which is public.
        form = self.get_form(self.app.current_version,
                             data={'publish_immediately': False})
        eq_(form.is_valid(), True)
        form.save()
        self.app.reload()
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)


class TestAdminSettingsForm(TestAdmin):

    def setUp(self):
        super(TestAdminSettingsForm, self).setUp()
        self.data = {'position': 1}
        self.user = UserProfile.objects.get(username='admin')
        self.request = RequestFactory()
        self.request.user = self.user
        self.request.groups = ()
        self.kwargs = {'instance': self.webapp, 'request': self.request}

    @mock.patch('mkt.developers.forms.index_webapps.delay')
    def test_reindexed(self, index_webapps_mock):
        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)
        index_webapps_mock.assert_called_with([self.webapp.id])

    def test_reinclude_rated_games(self):
        """
        Adding a content rating for a game in a region should remove the
        regional exclusion for that region.
        """

        # List it in the Games category.
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        self.webapp.addoncategory_set.create(category=cat)

        self.log_in_with('Apps:Configure')

        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)

        excluded_regions = [
            x.id for x in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS
        ]

        # After the form was saved, it should be excluded in Brazil.
        self.assertSetEqual(
            self.webapp.addonexcludedregion.values_list('region', flat=True),
            excluded_regions)

        # Add Brazil content rating.
        rb_br = mkt.regions.BR.ratingsbodies[0]
        br_0_idx = mkt.ratingsbodies.ALL_RATINGS.index(rb_br.ratings[0])
        self.data['app_ratings'] = [br_0_idx]

        # Post the form again.
        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)

        self.webapp = self.webapp.reload()

        # Notice the Brazilian region exclusion is now gone.
        excluded_regions.remove(mkt.regions.BR.id)
        self.assertSetEqual(
            self.webapp.addonexcludedregion.values_list('region', flat=True),
            excluded_regions)

    def test_exclude_unrated_games_when_removing_content_rating(self):
        """
        Removing a content rating for a game in Brazil should exclude that
        game in Brazil only.
        """

        self.log_in_with('Apps:Configure')
        rb_br = mkt.regions.BR.ratingsbodies[0]
        ContentRating.objects.create(addon=self.webapp, ratings_body=rb_br.id,
                                     rating=rb_br.ratings[0].id)

        rb_de = mkt.regions.DE.ratingsbodies[0]
        ContentRating.objects.create(addon=self.webapp, ratings_body=rb_de.id,
                                     rating=rb_de.ratings[0].id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.webapp, category=games)

        # Remove Brazil but keep Germany.
        de_0_idx = mkt.ratingsbodies.ALL_RATINGS.index(rb_de.ratings[0])
        self.data['app_ratings'] = [de_0_idx]

        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)

        regions = self.webapp.get_region_ids()
        for region in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS:
            if region == mkt.regions.BR:
                assert region.id not in regions, (
                    'should not be listed in %s' % region.slug)
            else:
                assert region.id in regions, (
                    'should be listed in %s' % region.slug)

    def test_adding_tags(self):
        self.data.update({'tags': 'tag one, tag two'})
        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)

        eq_(self.webapp.tags.count(), 2)
        self.assertSetEqual(
            self.webapp.tags.values_list('tag_text', flat=True),
            ['tag one', 'tag two'])

    def test_removing_tags(self):
        Tag(tag_text='tag one').save_tag(self.webapp)
        eq_(self.webapp.tags.count(), 1)

        self.data.update({'tags': 'tag two, tag three'})
        form = forms.AdminSettingsForm(self.data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save(self.webapp)

        eq_(self.webapp.tags.count(), 2)
        self.assertSetEqual(
            self.webapp.tags.values_list('tag_text', flat=True),
            ['tag two', 'tag three'])
