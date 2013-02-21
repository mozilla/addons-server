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
from amo.tests import app_factory
from amo.tests.test_helpers import get_image_path
from addons.models import Addon, AddonCategory, Category
from files.helpers import copyfileobj

import mkt
from mkt.developers import forms
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
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        shutil.copyfile(get_image_path(name), os.path.join(self.dest, name))
        assert form.is_valid(), form.errors
        form.save(self.addon)
        assert update_mock.called

    def test_preview_size(self):
        name = 'non-animated.gif'
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        with storage.open(os.path.join(self.dest, name), 'wb') as f:
            copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid(), form.errors
        form.save(self.addon)
        eq_(self.addon.previews.all()[0].sizes,
            {u'image': [250, 297], u'thumbnail': [180, 214]})

    def check_file_type(self, type_):
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': type_,
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


class TestRegionForm(amo.tests.WebappTestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        super(TestRegionForm, self).setUp()
        self.request = RequestFactory()
        self.kwargs = {'product': self.app}

    def test_initial_empty(self):
        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], mkt.regions.REGION_IDS)
        eq_(form.initial['other_regions'], True)

    def test_initial_excluded_in_region(self):
        AER.objects.create(addon=self.app,
                                           region=mkt.regions.BR.id)

        regions = list(mkt.regions.REGION_IDS)
        regions.remove(mkt.regions.BR.id)

        eq_(self.get_app().get_region_ids(), regions)

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], regions)
        eq_(form.initial['other_regions'], True)

    def test_initial_excluded_in_regions_and_future_regions(self):
        for region in [mkt.regions.BR, mkt.regions.UK, mkt.regions.WORLDWIDE]:
            AER.objects.create(addon=self.app,
                                               region=region.id)

        regions = list(mkt.regions.REGION_IDS)
        regions.remove(mkt.regions.BR.id)
        regions.remove(mkt.regions.UK.id)

        eq_(self.get_app().get_region_ids(), regions)

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(form.initial['regions'], regions)
        eq_(form.initial['other_regions'], False)

    def test_disable_regions_on_paid(self):
        eq_(self.app.get_region_ids(), mkt.regions.REGION_IDS)

        self.app.update(premium_type=amo.ADDON_PREMIUM)
        form = forms.RegionForm(data=None, **self.kwargs)
        assert form.has_inappropriate_regions()
        assert not form.is_valid()

        form = forms.RegionForm(
            data={'regions': mkt.regions.ALL_PAID_REGION_IDS}, **self.kwargs)
        assert form.has_inappropriate_regions()
        assert form.is_valid(), form.errors
        form.save()

        self.assertSetEqual(self.app.get_region_ids(),
                            mkt.regions.ALL_PAID_REGION_IDS)

        form = forms.RegionForm(data=None, **self.kwargs)
        assert not form.has_inappropriate_regions()

    def test_worldwide_only(self):
        form = forms.RegionForm(data={'other_regions': 'on'}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), [mkt.regions.WORLDWIDE.id])

    def test_no_regions(self):
        form = forms.RegionForm(data={}, **self.kwargs)
        assert not form.is_valid()
        eq_(form.errors,
            {'__all__': ['You must select at least one region or '
                         '"Other and new regions."']})

    def test_exclude_each_region(self):
        """Test that it's possible to exclude each region."""

        for region_id in mkt.regions.REGION_IDS:
            if region_id == mkt.regions.WORLDWIDE.id:
                continue

            to_exclude = list(mkt.regions.REGION_IDS)
            to_exclude.remove(region_id)

            form = forms.RegionForm(
                data={'regions': to_exclude,
                      'other_regions': True}, **self.kwargs)
            assert form.is_valid(), form.errors
            form.save()

            eq_(self.app.get_region_ids(False), to_exclude)

    def test_brazil_games_excluded(self):
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': True}, **self.kwargs)

        # Developers should still be able to save form OK, even
        # if they pass a bad region. Think of the grandfathered developers.
        assert form.is_valid(), form.errors
        form.save()

        # No matter what the developer tells us, still exclude Brazilian
        # games.
        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(set(form.initial['regions']),
            set(mkt.regions.REGION_IDS) -
            set([mkt.regions.BR.id, mkt.regions.WORLDWIDE.id]))
        eq_(form.initial['other_regions'], True)

    def test_brazil_games_already_excluded(self):
        AER.objects.create(addon=self.app, region=mkt.regions.BR.id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': True}, **self.kwargs)

        assert form.is_valid()
        form.save()

        form = forms.RegionForm(data=None, **self.kwargs)
        eq_(set(form.initial['regions']),
            set(mkt.regions.REGION_IDS) -
            set([mkt.regions.BR.id, mkt.regions.WORLDWIDE.id]))
        eq_(form.initial['other_regions'], True)

    def test_brazil_games_with_content_rating(self):
        # This game has a government content rating!
        rb = mkt.regions.BR.ratingsbodies[0]
        ContentRating.objects.create(
            addon=self.app, ratings_body=rb.id, rating=rb.ratings[0].id)

        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        AddonCategory.objects.create(addon=self.app, category=games)

        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': 'on'}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)

    def test_exclude_worldwide(self):
        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': False}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.REGION_IDS)

    def test_reinclude_region(self):
        AER.objects.create(addon=self.app, region=mkt.regions.BR.id)

        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': True}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)

    def test_reinclude_worldwide(self):
        AER.objects.create(addon=self.app, region=mkt.regions.WORLDWIDE.id)

        form = forms.RegionForm(data={'regions': mkt.regions.REGION_IDS,
                                      'other_regions': True}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.app.get_region_ids(True), mkt.regions.ALL_REGION_IDS)


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
            [u'Packaged app too large for submission.',
             u'Packages must be less than 5 bytes.'])


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
