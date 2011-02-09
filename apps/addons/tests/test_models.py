# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import itertools
from urlparse import urlparse

from django import forms
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.utils import translation

from mock import patch, patch_object
from nose.tools import eq_, assert_not_equal
from nose import SkipTest
import test_utils

import amo
import files.tests
from amo import set_user
from amo.signals import _connect, _disconnect
from addons.models import (Addon, AddonCategory, AddonDependency,
                           AddonRecommendation, AddonType, BlacklistedGuid,
                           Category, Charity, Feature, Persona, Preview)
from applications.models import Application, AppVersion
from devhub.models import ActivityLog
from files.models import File, Platform
from reviews.models import Review
from translations.models import TranslationSequence
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version
from services import update


class TestAddonManager(test_utils.TestCase):
    fixtures = ['base/addon_5299_gcal', 'addons/test_manager']

    def test_featured(self):
        featured = Addon.objects.featured(amo.FIREFOX)[0]
        eq_(featured.id, 1)
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 1)

    def test_listed(self):
        Addon.objects.filter(id=5299).update(disabled_by_user=True)
        # Should find one addon.
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC)
        eq_(len(q.all()), 1)

        addon = q[0]
        eq_(addon.id, 1)

        # Disabling hides it.
        addon.disabled_by_user = True
        addon.save()
        eq_(q.count(), 0)

        # If we search for public or unreviewed we find it.
        addon.disabled_by_user = False
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        eq_(q.count(), 0)
        eq_(Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                 amo.STATUS_UNREVIEWED).count(), 1)

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        eq_(q.count(), 0)

    def test_public(self):
        public = Addon.objects.public()
        for a in public:
            assert_not_equal(
                a.id, 3, 'public() must not return unreviewed add-ons')

    def test_unreviewed(self):
        """
        Tests for unreviewed addons.
        """
        exp = Addon.objects.unreviewed()

        for addon in exp:
            assert addon.status in amo.UNREVIEWED_STATUSES, (
                    "unreviewed() must return unreviewed addons.")


class TestAddonModels(test_utils.TestCase):
    fixtures = ['base/apps',
                'base/featured',
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple.json',
                'base/addon_4594_a9',
                'base/addon_4664_twitterbar',
                'base/thunderbird',
                'addons/featured',
                'addons/invalid_latest_version',
                'addons/blacklisted']

    def setUp(self):
        TranslationSequence.objects.create(id=99243)
        # Addon._feature keeps an in-process cache we need to clear.
        if hasattr(Addon, '_feature'):
            del Addon._feature

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.current_version.id, 81551)

    def test_current_version_listed(self):
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version.id, 89774)

    def test_current_version_listed_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version, None)

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        eq_(a.current_beta_version.id, 50000)

    def test_current_version_mixed_statuses(self):
        """Mixed file statuses are evil (bug 558237)."""
        a = Addon.objects.get(pk=3895)
        # Last version has pending files, so second to last version is
        # considered "current".
        eq_(a.current_version.id, 78829)

        # Fix file statuses on last version.
        v = Version.objects.get(pk=98217)
        v.files.update(status=amo.STATUS_PUBLIC)

        # Wipe caches.
        cache.clear()
        a.update_current_version()

        # Make sure the updated version is now considered current.
        eq_(a.current_version.id, v.id)

    def test_delete(self):
        """Test deleting add-ons."""
        a = Addon.objects.get(pk=3615)
        a.name = u'é'
        a.delete('bye')
        eq_(len(mail.outbox), 1)
        assert BlacklistedGuid.objects.filter(guid=a.guid)

    def test_delete_searchengine(self):
        """
        Test deleting searchengines (which have no guids) should not barf up
        the deletion machine.
        """
        a = Addon.objects.get(pk=4594)
        a.delete('bye')
        eq_(len(mail.outbox), 1)

    def test_delete_status_gone_wild(self):
        """
        Test deleting add-ons where the higheststatus is zero, but there's a
        non-zero status.
        """
        a = Addon.objects.get(pk=3615)
        a.status = amo.STATUS_UNREVIEWED
        a.highest_status = 0
        a.delete('bye')
        eq_(len(mail.outbox), 1)
        assert BlacklistedGuid.objects.filter(guid=a.guid)

    def test_delete_incomplete(self):
        """Test deleting incomplete add-ons."""
        a = Addon.objects.get(pk=3615)
        a.status = 0
        a.highest_status = 0
        a.save()
        a.delete(None)
        eq_(len(mail.outbox), 0)
        assert not BlacklistedGuid.objects.filter(guid=a.guid)

    def test_incompatible_latest_apps(self):
        a = Addon.objects.get(pk=3615)
        eq_(a.incompatible_latest_apps(), [])

        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.get(pk=97)  # Firefox 2.0
        av.save()

        a = Addon.objects.get(pk=3615)
        eq_(a.incompatible_latest_apps(), [amo.FIREFOX])

        # Check a search engine addon.
        a = Addon.objects.get(pk=4594)
        eq_(a.incompatible_latest_apps(), [])

    def test_icon_url(self):
        """
        Tests for various icons.
        1. Test for an icon that exists.
        2. Test for default THEME icon.
        3. Test for default non-THEME icon.
        """
        a = Addon.objects.get(pk=3615)
        expected = (settings.ADDON_ICON_URL % (3615, 0)).rstrip('/0')
        assert a.icon_url.startswith(expected)
        a = Addon.objects.get(pk=6704)
        a.icon_type = None
        assert a.icon_url.endswith('/icons/default-theme.png'), (
                "No match for %s" % a.icon_url)
        a = Addon.objects.get(pk=3615)
        a.icon_type = None

        assert a.icon_url.endswith('icons/default-32.png')

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=4664)
        a.thumbnail_url.index('/previews/thumbs/20/20397.png?modified=')
        a = Addon.objects.get(pk=5299)
        assert a.thumbnail_url.endswith('/icons/no-preview.png'), (
                "No match for %s" % a.thumbnail_url)

    def test_is_unreviewed(self):
        """Test if add-on is unreviewed or not"""
        # public add-on
        a = Addon.objects.get(pk=3615)
        assert not a.is_unreviewed(), 'public add-on: is_unreviewed=False'

        # unreviewed add-on
        a = Addon(status=amo.STATUS_UNREVIEWED)
        assert a.is_unreviewed(), 'sandboxed add-on: is_unreviewed=True'

        a.status = amo.STATUS_PENDING
        assert a.is_unreviewed(), 'pending add-on: is_unreviewed=True'

    def test_is_selfhosted(self):
        """Test if an add-on is listed or hosted"""
        # hosted
        a = Addon.objects.get(pk=3615)
        assert not a.is_selfhosted(), 'hosted add-on => !is_selfhosted()'

        # listed
        a.status = amo.STATUS_LISTED
        assert a.is_selfhosted(), 'listed add-on => is_selfhosted()'

    def test_is_featured(self):
        """Test if an add-on is globally featured"""
        a = Addon.objects.get(pk=1003)
        assert a.is_featured(amo.FIREFOX, 'en-US'), (
            'globally featured add-on not recognized')

    def test_is_category_featured(self):
        """Test if an add-on is category featured"""
        Feature.objects.filter(addon=1001).delete()
        a = Addon.objects.get(pk=1001)
        assert not a.is_featured(amo.FIREFOX, 'en-US')

        assert a.is_category_featured(amo.FIREFOX, 'en-US')

    def test_has_full_profile(self):
        """Test if an add-on's developer profile is complete (public)."""
        addon = lambda: Addon.objects.get(pk=3615)
        assert not addon().has_full_profile()

        a = addon()
        a.the_reason = 'some reason'
        a.save()
        assert not addon().has_full_profile()

        a.the_future = 'some future'
        a.save()
        assert addon().has_full_profile()

        a.the_reason = ''
        a.the_future = ''
        a.save()
        assert not addon().has_full_profile()

    def test_has_profile(self):
        """Test if an add-on's developer profile is (partially or entirely)
        completed.

        """
        addon = lambda: Addon.objects.get(pk=3615)
        assert not addon().has_profile()

        a = addon()
        a.the_reason = 'some reason'
        a.save()
        assert addon().has_profile()

        a.the_future = 'some future'
        a.save()
        assert addon().has_profile()

        a.the_reason = ''
        a.the_future = ''
        a.save()
        assert not addon().has_profile()

    def test_has_eula(self):
        addon = lambda: Addon.objects.get(pk=3615)
        assert addon().has_eula

        a = addon()
        a.eula = ''
        a.save()
        assert not addon().has_eula

        a.eula = 'eula'
        a.save()
        assert addon().has_eula

    def test_app_categories(self):
        addon = lambda: Addon.objects.get(pk=3615)

        c22 = Category.objects.get(id=22)
        c22.name = 'CCC'
        c22.save()
        c23 = Category.objects.get(id=23)
        c23.name = 'BBB'
        c23.save()
        c24 = Category.objects.get(id=24)
        c24.name = 'AAA'
        c24.save()

        cats = addon().all_categories
        eq_(cats, [c22, c23, c24])
        for cat in cats:
            eq_(cat.application.id, amo.FIREFOX.id)

        cats = [c24, c23, c22]
        app_cats = [(amo.FIREFOX, cats)]
        eq_(addon().app_categories, app_cats)

        tb = Application.objects.get(id=amo.THUNDERBIRD.id)
        c = Category(application=tb, name='XXX', type=addon().type, count=1,
                     weight=1)
        c.save()
        AddonCategory.objects.create(addon=addon(), category=c)
        c24.save()  # Clear the app_categories cache.
        app_cats += [(amo.THUNDERBIRD, [c])]
        eq_(addon().app_categories, app_cats)

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=999)
        version = addon.current_version
        new_review = Review(version=version, user=u, rating=2, body='hello',
                            addon=addon)
        new_review.save()
        new_reply = Review(version=version, user=addon.authors.all()[0],
                           addon=addon, reply_to=new_review,
                           rating=2, body='my reply')
        new_reply.save()

        review_list = [r.pk for r in addon.reviews]

        assert new_review.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')

    def test_takes_contributions(self):
        a = Addon(status=amo.STATUS_PUBLIC, wants_contributions=True,
                  paypal_id='$$')
        assert a.takes_contributions

        a.status = amo.STATUS_UNREVIEWED
        assert not a.takes_contributions
        a.status = amo.STATUS_PUBLIC

        a.wants_contributions = False
        assert not a.takes_contributions
        a.wants_contributions = True

        a.paypal_id = None
        assert not a.takes_contributions

        a.charity_id = 12
        assert a.takes_contributions

    def test_show_beta(self):
        # Addon.current_beta_version will be empty, so show_beta is False.
        a = Addon(status=amo.STATUS_PUBLIC)
        assert not a.show_beta

    @patch('addons.models.Addon.current_beta_version')
    def test_show_beta_with_beta_version(self, beta_mock):
        beta_mock.return_value = object()
        # Fake current_beta_version to return something truthy.
        a = Addon(status=amo.STATUS_PUBLIC)
        assert a.show_beta

        # We have a beta version but status has to be public.
        a.status = amo.STATUS_UNREVIEWED
        assert not a.show_beta

    def test_update_logs(self):
        addon = Addon.objects.get(id=3615)
        set_user(UserProfile.objects.all()[0])
        addon.versions.all().delete()

        entries = ActivityLog.objects.all()
        eq_(entries[0].action, amo.LOG.CHANGE_STATUS.id)

    def test_can_request_review_waiting_period(self):
        now = datetime.now()
        a = Addon.objects.create(type=1)
        v = Version.objects.create(addon=a)
        # The first LITE version is only 5 days old, no dice.
        first_f = File.objects.create(status=amo.STATUS_LITE, version=v)
        first_f.update(datestatuschanged=now - timedelta(days=5))
        # TODO(andym): can this go in Addon.objects.create? bug 618444
        a.update(status=amo.STATUS_LITE)
        eq_(a.can_request_review(), ())

        # Now the first LITE is > 10 days old, change can happen.
        first_f.update(datestatuschanged=now - timedelta(days=11))
        # Add a second file, to be sure that we test the date
        # of the first created file.
        second_f = File.objects.create(status=amo.STATUS_LITE, version=v)
        second_f.update(datestatuschanged=now - timedelta(days=5))
        v = Version.objects.create(addon=a)
        eq_(a.status, amo.STATUS_LITE)
        eq_(a.can_request_review(), (amo.STATUS_PUBLIC,))

    def setup_files(self, status):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=status, version=version)
        return addon, version

    def test_can_alter_in_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_LITE)
        version.save()
        eq_(addon.status, amo.STATUS_LITE)

    def test_removing_public(self):
        addon, version = self.setup_files(amo.STATUS_UNREVIEWED)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        eq_(addon.status, amo.STATUS_UNREVIEWED)

    def test_removing_public_with_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        eq_(addon.status, amo.STATUS_LITE)

    def test_can_request_review_no_files(self):
        addon = Addon.objects.get(pk=3615)
        addon.versions.all()[0].files.all().delete()
        eq_(addon.can_request_review(), ())

    def check(self, status, exp, kw={}):
        addon = Addon.objects.get(pk=3615)
        changes = {'status': status, 'disabled_by_user': False}
        changes.update(**kw)
        addon.update(**changes)
        eq_(addon.can_request_review(), exp)

    def test_can_request_review_null(self):
        self.check(amo.STATUS_NULL, (amo.STATUS_LITE, amo.STATUS_PUBLIC))

    def test_can_request_review_null_disabled(self):
        self.check(amo.STATUS_NULL, (), {'disabled_by_user': True})

    def test_can_request_review_unreviewed(self):
        self.check(amo.STATUS_UNREVIEWED, (amo.STATUS_PUBLIC,))

    def test_can_request_review_nominated(self):
        self.check(amo.STATUS_NOMINATED, (amo.STATUS_LITE,))

    def test_can_request_review_public(self):
        self.check(amo.STATUS_PUBLIC, ())

    def test_can_request_review_disabled(self):
        self.check(amo.STATUS_DISABLED, ())

    def test_can_request_review_lite(self):
        self.check(amo.STATUS_LITE, (amo.STATUS_PUBLIC,))

    def test_can_request_review_lite_and_nominated(self):
        self.check(amo.STATUS_LITE_AND_NOMINATED, ())

    def test_can_request_review_purgatory(self):
        self.check(amo.STATUS_PURGATORY, (amo.STATUS_LITE, amo.STATUS_PUBLIC,))

    def test_none_homepage(self):
        # There was an odd error when a translation was set to None.
        Addon.objects.create(homepage=None, type=amo.ADDON_EXTENSION)

    def test_slug_isdigit(self):
        a = Addon.objects.create(type=1, name='xx', slug='123')
        eq_(a.slug, '123~')

        a.slug = '44'
        a.save()
        eq_(a.slug, '44~')

    def test_slug_isblacklisted(self):
        # When an addon is uploaded, it doesn't use the form validation,
        # so we'll just mangle the slug if its blacklisted.
        a = Addon.objects.create(type=1, name='xx', slug='validate')
        eq_(a.slug, 'validate~')

        a.slug = 'validate'
        a.save()
        eq_(a.slug, 'validate~')

    def delete(self):
        addon = Addon.objects.get(id=3615)
        eq_(len(mail.outbox), 0)
        addon.delete('so long and thanks for all the fish')
        eq_(len(mail.outbox), 1)

    def test_delete_to(self):
        self.delete()
        eq_(mail.outbox[0].to, [settings.FLIGTAR])

    def test_delete_by(self):
        try:
            user = Addon.objects.get(id=3615).authors.all()[0]
            set_user(user)
            self.delete()
            assert 'DELETED BY: 55021' in mail.outbox[0].body
        finally:
            set_user(None)

    def test_delete_by_unknown(self):
        self.delete()
        assert 'DELETED BY: Unknown' in mail.outbox[0].body

    def test_view_source(self):
        # view_source should default to True.
        a = Addon.objects.create(type=1)
        assert a.view_source


class TestCategoryModel(test_utils.TestCase):

    def test_category_url(self):
        """Every type must have a url path for its categories."""
        for t in amo.ADDON_TYPE.keys():
            if t == amo.ADDON_DICT:
                continue  # Language packs don't have categories.
            cat = Category(type=AddonType(id=t), slug='omg')
            assert cat.get_url_path()


class TestPersonaModel(test_utils.TestCase):

    def test_image_urls(self):
        mypersona = Persona(id=1234, persona_id=9876)
        assert mypersona.thumb_url.endswith('/7/6/9876/preview.jpg')
        assert mypersona.preview_url.endswith('/7/6/9876/preview_large.jpg')

    def test_update_url(self):
        p = Persona(id=1234, persona_id=9876)
        assert p.update_url.endswith('9876')


class TestPreviewModel(test_utils.TestCase):

    fixtures = ['base/previews']

    def test_as_dict(self):
        expect = ['caption', 'full', 'thumbnail']
        reality = sorted(Preview.objects.all()[0].as_dict().keys())
        eq_(expect, reality)


class TestAddonRecommendations(test_utils.TestCase):
    fixtures = ['base/addon-recs']

    def test_scores(self):
        ids = [5299, 1843, 2464, 7661, 5369]
        scores = AddonRecommendation.scores(ids)
        q = AddonRecommendation.objects.filter(addon__in=ids)
        for addon, recs in itertools.groupby(q, lambda x: x.addon_id):
            for rec in recs:
                eq_(scores[addon][rec.other_addon_id], rec.score)


class TestAddonDependencies(test_utils.TestCase):
    fixtures = ['base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple',
                'base/addon_4664_twitterbar']

    def test_dependencies(self):
        ids = [3615, 3723, 4664, 6704]
        a = Addon.objects.get(id=5299)

        for dependent_id in ids:
            AddonDependency(addon=a,
                dependent_addon=Addon.objects.get(id=dependent_id)).save()

        eq_(sorted([a.id for a in a.dependencies.all()]), sorted(ids))


class TestListedAddonTwoVersions(test_utils.TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestFlushURLs(test_utils.TestCase):
    fixtures = ['base/addon_5579',
                'base/previews',
                'base/addon_4664_twitterbar',
                'addons/persona']

    def setUp(self):
        settings.ADDON_ICON_URL = (
            '%s/%s/%s/images/addon_icon/%%d/?modified=%%s' % (
            settings.STATIC_URL, settings.LANGUAGE_CODE, settings.DEFAULT_APP))
        settings.PREVIEW_THUMBNAIL_URL = (settings.STATIC_URL +
            '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
        settings.PREVIEW_FULL_URL = (settings.STATIC_URL +
            '/img/uploads/previews/full/%s/%d.png?modified=%d')
        _connect()

    def tearDown(self):
        _disconnect()

    def is_url_hashed(self, url):
        return urlparse(url).query.find('modified') > -1

    @patch('amo.tasks.flush_front_end_cache_urls.apply_async')
    def test_addon_flush(self, flush):
        addon = Addon.objects.get(pk=159)
        addon.icon_type = "image/png"
        addon.save()

        for url in (addon.thumbnail_url, addon.icon_url):
            assert url in flush.call_args[1]['args'][0]
            assert self.is_url_hashed(url), url

    @patch('amo.tasks.flush_front_end_cache_urls.apply_async')
    def test_preview_flush(self, flush):
        addon = Addon.objects.get(pk=4664)
        preview = addon.previews.all()[0]
        preview.save()
        for url in (preview.thumbnail_url, preview.image_url):
            assert url in flush.call_args[1]['args'][0]
            assert self.is_url_hashed(url), url


class TestUpdate(test_utils.TestCase):
    fixtures = ['addons/update',
                'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.get(id=1865)
        self.platform = None
        self.version_int = 3069900200100

        self.app = Application.objects.get(id=1)
        self.version_1_0_2 = 66463
        self.version_1_1_3 = 90149
        self.version_1_2_0 = 105387
        self.version_1_2_1 = 112396
        self.version_1_2_2 = 115509

        self.cursor = connection.cursor()

    def get(self, *args):
        up = update.Update({
            'id': self.addon.guid,
            'version': args[0],
            'appID': args[2].guid,
            'appVersion': 1,  # this is going to be overridden
            'appOS': args[3].api_name if args[3] else '',
            'reqVersion': '',
            })
        up.cursor = self.cursor
        assert up.is_valid()
        up.data['version_int'] = args[1]
        up.get_update()

        self.up = up
        return (up.data['row'].get('version_id'),
                up.data['row'].get('file_id'))

    def test_low_client(self):
        """Test a low client number. 86 is version 3.0a1 of Firefox,
        which means we have version int of 3000000001100
        and hence version 1.0.2 of the addon."""
        version, file = self.get('', '3000000001100',
                                 self.app, self.platform)
        eq_(version, self.version_1_0_2)

    def test_new_client(self):
        """Test a high client number. 291 is version 3.0.12 of Firefox,
        which means we have a version int of 3069900200100
        and hence version 1.2.2 of the addon."""
        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_2)

    def test_new_client_ordering(self):
        """Given the following:
        * Version 15 (1 day old), max application_version 3.6*
        * Version 12 (1 month old), max application_version 3.7a
        We want version 15, even though version 12 is for a higher version.
        This was found in https://bugzilla.mozilla.org/show_bug.cgi?id=615641.
        """
        application_version = ApplicationsVersions.objects.get(pk=77550)
        application_version.max_id = 350
        application_version.save()

        # Version 1.2.2 is now a lower max version.
        application_version = ApplicationsVersions.objects.get(pk=88490)
        application_version.max_id = 329
        application_version.save()

        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_2)

    def test_public_not_beta(self):
        """If the addon status is public and you are not asking
        for a beta version, then you get a public version."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.status = amo.STATUS_PENDING
            file.save()
        # We've made 1.2.2 pending so that it will not be selected
        # and the highest version is 1.2.1

        eq_(self.addon.status, amo.STATUS_PUBLIC)
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_public_beta(self):
        """If the addon status is public and you are asking
        for a beta version and there are no beta upgrades, then
        you won't get an update."""
        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        assert not version

    def test_can_downgrade(self):
        """Check that we can downgrade."""
        self.change_status(self.version_1_2_0, amo.STATUS_PENDING)

        Version.objects.filter(pk__gte=self.version_1_2_1).delete()
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)

        eq_(version, self.version_1_1_3)

    def test_public_pending_not_exists(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking something public."""
        version = Version.objects.get(pk=self.version_1_2_0)
        version.version = '1.2beta'
        version.save()

        # set the current version to pending
        file = version.files.all()[0]
        file.status = amo.STATUS_PENDING
        file.save()

        self.change_status(self.version_1_2_2, amo.STATUS_PENDING)
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)

        eq_(version, self.version_1_2_1)

    def test_public_pending_no_file_no_beta(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. If there are no files,
        we look for a beta. That does not exist."""
        version = Version.objects.get(pk=self.version_1_2_0)
        version.version = '1.2beta'
        version.save()

        version.files.all().delete()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        assert not version

    def change_status(self, version, status):
        version = Version.objects.get(pk=version)
        file = version.files.all()[0]
        file.status = status
        file.save()
        return version

    def test_public_pending_no_file_has_beta(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. If there are no files,
        we look for a beta. That does exist."""
        version = Version.objects.get(pk=self.version_1_2_0)
        version.version = '1.2beta'
        version.save()

        version.files.all().delete()
        self.change_status(self.version_1_2_1, amo.STATUS_BETA)

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_public_pending_exists(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for a public version."""
        # set the current version to pending
        version = self.change_status(self.version_1_2_0, amo.STATUS_PENDING)
        version.update(version='1.2beta')
        self.change_status(self.version_1_2_2, amo.STATUS_BETA)

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_not_public(self):
        """If the addon status is not public, then the update only
        looks for files within that one version."""
        self.addon.update(status=amo.STATUS_PENDING)
        version, file = self.get('1.2.1', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_platform_does_not_exist(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_platform_exists(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version, self.version_1_2_2)

    def test_file_for_platform(self):
        """If client passes a platform, make sure we get the right file."""
        version = Version.objects.get(pk=self.version_1_2_2)
        file_one = version.files.all()[0]
        file_one.platform_id = amo.PLATFORM_LINUX.id
        file_one.save()

        file_two = File(version=version, filename='foo', hash='bar',
                        platform_id=amo.PLATFORM_WIN.id,
                        status=amo.STATUS_PUBLIC)
        file_two.save()
        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version,  self.version_1_2_2)
        eq_(file, file_one.pk)

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_WIN)
        eq_(version,  self.version_1_2_2)
        eq_(file, file_two.pk)

    def test_file_preliminary(self):
        """If there's a newer file in prelim. review it won't show up. This is
        a test for https://bugzilla.mozilla.org/show_bug.cgi?id=620749"""
        version = Version.objects.get(pk=self.version_1_2_2)
        file = version.files.all()[0]
        file.status = amo.STATUS_LITE
        file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version, self.version_1_2_1)

    def test_file_preliminary_addon(self):
        """If the addon is in prelim. review, show the highest file with
        public., which in this case is 1.2.1"""
        for status in amo.LITE_STATUSES:
            self.addon.update(status=status)

            self.change_status(self.version_1_2_1, amo.STATUS_LITE)
            version, file = self.get('1.2', self.version_int,
                                     self.app, amo.PLATFORM_LINUX)
            eq_(version, self.version_1_2_1)

class TestAddonFromUpload(files.tests.UploadTest):
    fixtures = ('base/apps', 'base/users')

    def setUp(self):
        super(TestAddonFromUpload, self).setUp()
        u = UserProfile.objects.get(pk=999)
        set_user(u)
        self.platform = Platform.objects.create(id=amo.PLATFORM_MAC.id)
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application_id=1, version=version)

    def test_blacklisted_guid(self):
        BlacklistedGuid.objects.create(guid='guid@xpi')
        with self.assertRaises(forms.ValidationError) as e:
            Addon.from_upload(self.get_upload('extension.xpi'),
                              [self.platform])
        eq_(e.exception.messages, ['Duplicate UUID found.'])

    def test_xpi_attributes(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        eq_(addon.name, 'xpi name')
        eq_(addon.guid, 'guid@xpi')
        eq_(addon.type, amo.ADDON_EXTENSION)
        eq_(addon.status, amo.STATUS_NULL)
        eq_(addon.homepage, 'http://homepage.com')
        eq_(addon.summary, 'xpi description')
        eq_(addon.description, None)
        eq_(addon.slug, 'xpi-name')

    def test_xpi_version(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        v = addon.versions.get()
        eq_(v.version, '0.1')
        eq_(v.files.get().platform_id, self.platform.id)
        eq_(v.files.get().status, amo.STATUS_UNREVIEWED)

    def test_xpi_for_multiple_platforms(self):
        platforms = [Platform.objects.get(pk=amo.PLATFORM_LINUX.id),
                     Platform.objects.get(pk=amo.PLATFORM_MAC.id)]
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  platforms)
        v = addon.versions.get()
        eq_(sorted([f.platform.id for f in v.all_files]),
            sorted([p.id for p in platforms]))

    def test_search_attributes(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.name, 'search tool')
        eq_(addon.guid, None)
        eq_(addon.type, amo.ADDON_SEARCH)
        eq_(addon.status, amo.STATUS_NULL)
        eq_(addon.homepage, None)
        eq_(addon.description, None)
        eq_(addon.slug, 'search-tool')
        eq_(addon.summary, 'Search Engine for Firefox')

    def test_search_version(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        v = addon.versions.get()
        eq_(v.version, datetime.now().strftime('%Y%m%d'))
        eq_(v.files.get().platform_id, amo.PLATFORM_ALL.id)
        eq_(v.files.get().status, amo.STATUS_UNREVIEWED)

    def test_no_homepage(self):
        addon = Addon.from_upload(self.get_upload('extension-no-homepage.xpi'),
                                  [self.platform])
        eq_(addon.homepage, None)

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.default_locale, 'en-US')

        translation.activate('es-ES')
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.default_locale, 'es-ES')
        translation.deactivate()


REDIRECT_URL = 'http://outgoing.mozilla.org/v1/'


class TestCharity(test_utils.TestCase):
    fixtures = ['base/charity.json']

    @patch_object(settings._wrapped, 'REDIRECT_URL', REDIRECT_URL)
    def test_url(self):
        charity = Charity(name="a", paypal="b", url="http://foo.com")
        charity.save()
        assert charity.outgoing_url.startswith(REDIRECT_URL)

    @patch_object(settings._wrapped, 'REDIRECT_URL', REDIRECT_URL)
    def test_url_foundation(self):
        foundation = Charity.objects.get(pk=amo.FOUNDATION_ORG)
        assert not foundation.outgoing_url.startswith(REDIRECT_URL)
