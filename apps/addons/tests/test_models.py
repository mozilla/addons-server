# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import itertools
from urlparse import urlparse

from django import forms
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.utils import translation

from mock import patch, patch_object
from nose.tools import eq_, assert_not_equal
import test_utils

import amo
import files.tests
from amo import set_user
from amo.signals import _connect, _disconnect
from addons.models import (Addon, AddonCategory, AddonDependency,
                           AddonRecommendation, AddonType, BlacklistedGuid,
                           Category, Charity, Feature, FrozenAddon, Persona,
                           Preview)
from applications.models import Application, AppVersion
from devhub.models import ActivityLog
from files.models import File, Platform
from reviews.models import Review
from translations.models import TranslationSequence
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version


class TestAddonManager(test_utils.TestCase):
    fixtures = ['base/addon_5299_gcal', 'addons/test_manager']

    def setUp(self):
        set_user(None)

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
        a.update_version()

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

    def newlines_helper(self, string_before):
        addon = Addon.objects.get(pk=3615)
        addon.privacy_policy = string_before
        addon.save()
        return addon.privacy_policy.localized_string_clean

    def test_newlines_normal(self):
        before = ("Paragraph one.\n"
                  "This should be on the very next line.\n\n"
                  "Should be two nl's before this line.\n\n\n"
                  "Should be three nl's before this line.\n\n\n\n"
                  "Should be four nl's before this line.")

        after = before # Nothing special; this shouldn't change.

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul(self):
        before = ("<ul>\n\n"
                  "<li>No nl's between the ul and the li.</li>\n\n"
                  "<li>No nl's between li's.\n\n"
                  "But there should be two before this line.</li>\n\n"
                  "</ul>")

        after = ("<ul>"
                 "<li>No nl's between the ul and the li.</li>"
                 "<li>No nl's between li's.\n\n"
                 "But there should be two before this line.</li>"
                 "</ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul_tight(self):
        before = ("There should be one nl between this and the ul.\n"
                  "<ul><li>test</li><li>test</li></ul>\n"
                  "There should be no nl's above this line.")

        after = ("There should be one nl between this and the ul.\n"
                 "<ul><li>test</li><li>test</li></ul>"
                 "There should be no nl's above this line.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul_loose(self):
        before = ("There should be two nl's between this and the ul.\n\n"
                  "<ul><li>test</li><li>test</li></ul>\n\n"
                  "There should be one nl above this line.")

        after = ("There should be two nl's between this and the ul.\n\n"
                 "<ul><li>test</li><li>test</li></ul>\n"
                 "There should be one nl above this line.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_blockquote_tight(self):
        before = ("There should be one nl below this.\n"
                  "<blockquote>Hi</blockquote>\n"
                  "There should be no nl's above this.")

        after = ("There should be one nl below this.\n"
                 "<blockquote>Hi</blockquote>"
                 "There should be no nl's above this.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_blockquote_loose(self):
        before = ("There should be two nls below this.\n\n"
                  "<blockquote>Hi</blockquote>\n\n"
                  "There should be one nl above this.")

        after = ("There should be two nls below this.\n\n"
                 "<blockquote>Hi</blockquote>\n"
                 "There should be one nl above this.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_inline(self):
        before = ("If we end a paragraph w/ a <b>non-block-level tag</b>\n\n"
                  "<b>The newlines</b> should be kept")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_code_inline(self):
        before = ("Code tags aren't blocks.\n\n"
                  "<code>alert(test);</code>\n\n"
                  "See?")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_newlines(self):
        before = ("<ul><li>\nxx</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li>xx\n</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li>xx\nxx</li></ul>")
        after = ("<ul><li>xx\nxx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li></li></ul>")
        after = ("<ul><li></li></ul>")
        eq_(self.newlines_helper(before), after)

        # All together now
        before = ("<ul><li>\nxx</li> <li>xx\n</li> <li>xx\nxx</li> "
                  "<li></li>\n</ul>")

        after = ("<ul><li>xx</li> <li>xx</li> <li>xx\nxx</li> "
                 "<li></li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag(self):
        before = ("This is a <b></b> test!")
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag_nested(self):
        before = ("This is a <b><i></i></b> test!")
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag_block_nested(self):
        before = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>\ntest.")
        after = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag_block_nested_spaced(self):
        before = ("Test.\n\n<blockquote>\n\n<ul>\n\n<li>"
                  "</li>\n\n</ul>\n\n</blockquote>\ntest.")
        after = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_newlines_inline(self):
        before = ("<ul><li>\n<b>test\ntest\n\ntest</b>\n</li>"
                  "<li>Test <b>test</b> test.</li></ul>")

        after = ("<ul><li><b>test\ntest\n\ntest</b></li>"
                 "<li>Test <b>test</b> test.</li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_all_inline(self):
        before = ("Test with <b>no newlines</b> and <code>block level "
                  "stuff</code> to see what happens.")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_spaced_blocks(self):
        before = ("<blockquote>\n\n<ul>\n\n<li>\n\ntest\n\n</li>\n\n"
                  "</ul>\n\n</blockquote>")

        after = "<blockquote><ul><li>test</li></ul></blockquote>"

        eq_(self.newlines_helper(before), after)

    def test_newlines_spaced_inline(self):
        before = "Line.\n\n<b>\nThis line is bold.\n</b>\n\nThis isn't."
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_nested_inline(self):
        before = "<b>\nThis line is bold.\n\n<i>This is also italic</i></b>"
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_xss_script(self):
        before = "<script>\n\nalert('test');\n</script>"
        after = "&lt;script&gt;\n\nalert('test');\n&lt;/script&gt;"

        eq_(self.newlines_helper(before), after)

    def test_newlines_xss_inline(self):
        before = "<b onclick=\"alert('test');\">test</b>"
        after = "<b>test</b>"

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_link_doublequote(self):
        before = '<a href="http://google.com">test</a>'

        parsed = self.newlines_helper(before)

        assert parsed.endswith('google.com" rel="nofollow">test</a>')

    def test_newlines_attribute_singlequote(self):
        before = "<abbr title='laugh out loud'>lol</abbr>"
        after = '<abbr title="laugh out loud">lol</abbr>'

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_doublequote(self):
        before = '<abbr title="laugh out loud">lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_nestedquotes_doublesingle(self):
        before = '<abbr title="laugh \'out\' loud">lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_nestedquotes_singledouble(self):
        before = '<abbr title=\'laugh "out" loud\'>lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_b(self):
        before = ("<b>test")
        after = ("<b>test</b>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_b_wrapped(self):
        before = ("This is a <b>test")
        after = ("This is a <b>test</b>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_li(self):
        before = ("<ul><li>test</ul>")
        after = ("<ul><li>test</li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_faketag(self):
        before = "<madonna"
        after = ""

        eq_(self.newlines_helper(before), after)

    def test_newlines_correct_faketag(self):
        before = "<madonna>"
        after = "&lt;madonna&gt;"

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_tag(self):
        before = "<strong"
        after = ""

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_faketag_surrounded(self):
        before = "This is a <test of bleach"
        after = 'This is a &lt;test of="" bleach=""&gt;'

        # Output is ugly, but not much we can do.  Bleach+html5lib is adamant
        # this is a tag.
        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_tag_surrounded(self):
        before = "This is a <strong of bleach"
        after = "This is a <strong></strong>"

        # Bleach interprets 'of' and 'bleach' as attributes, and strips them.
        # Good? No.  Any way around it?  Not really.
        eq_(self.newlines_helper(before), after)

    def test_newlines_less_than(self):
        before = "3 < 5"
        after = "3 &lt; 5"

        eq_(self.newlines_helper(before), after)

    def test_newlines_less_than_tight(self):
        before = "abc 3<5 def"
        after = "abc 3&lt;5 def"

        eq_(self.newlines_helper(before), after)

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
        first_f.update(datestatuschanged=now - timedelta(days=5),
                       created=now - timedelta(days=20))
        # TODO(andym): can this go in Addon.objects.create? bug 618444
        a.update(status=amo.STATUS_LITE)
        eq_(a.can_request_review(), ())

        # Now the first LITE is > 10 days old, change can happen.
        first_f.update(datestatuschanged=now - timedelta(days=11))
        # Add a second file, to be sure that we test the date
        # of the first created file.
        second_f = File.objects.create(status=amo.STATUS_LITE, version=v)
        second_f.update(datestatuschanged=now - timedelta(days=5))
        eq_(a.status, amo.STATUS_LITE)
        eq_(a.can_request_review(), (amo.STATUS_PUBLIC,))

    def test_days_until_full_nomination(self):
        # Normalize to 12am for reliable day subtraction:
        now = datetime.now().date()
        a = Addon.objects.create(type=1)
        v = Version.objects.create(addon=a)
        f = File.objects.create(status=amo.STATUS_LITE, version=v)
        a.update(status=amo.STATUS_LITE)
        f.update(datestatuschanged=now - timedelta(days=4))
        eq_(a.days_until_full_nomination(), 6)
        f.update(datestatuschanged=now - timedelta(days=1))
        eq_(a.days_until_full_nomination(), 9)
        f.update(datestatuschanged=now - timedelta(days=10))
        eq_(a.days_until_full_nomination(), 0)
        f.update(datestatuschanged=now)
        eq_(a.days_until_full_nomination(), 10)
        # Only calculate days from first submitted version:
        f.update(datestatuschanged=now - timedelta(days=2),
                 created=now - timedelta(days=2))
        # Ignore this one:
        f2 = File.objects.create(status=amo.STATUS_LITE, version=v)
        f2.update(datestatuschanged=now - timedelta(days=1),
                  created=now - timedelta(days=1))
        eq_(a.days_until_full_nomination(), 8)
        # Wrong status:
        a.update(status=amo.STATUS_PUBLIC)
        f.update(datestatuschanged=now - timedelta(days=4))
        eq_(a.days_until_full_nomination(), 0)

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

    @patch('files.models.File.hide_disabled_file')
    def test_admin_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.status = amo.STATUS_PUBLIC
        a.save()
        assert not hide_mock.called

        a.status = amo.STATUS_DISABLED
        a.save()
        assert hide_mock.called

    @patch('files.models.File.hide_disabled_file')
    def test_user_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.disabled_by_user = False
        a.save()
        assert not hide_mock.called

        a.disabled_by_user = True
        a.save()
        assert hide_mock.called

    def test_set_nomination(self):
        a = Addon.objects.get(id=3615)
        a.update(status=amo.STATUS_NULL)
        for s in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED):
            a.versions.latest().update(nomination=None)
            a.update(status=s)
            assert a.versions.latest().nomination

    def test_nomination_no_version(self):
        # Check that the on_change method still works if there are no versions.
        a = Addon.objects.get(id=3615)
        a.versions.all().delete()
        a.update(status=amo.STATUS_NOMINATED)

    def test_nomination_already_set(self):
        addon = Addon.objects.get(id=3615)
        earlier = datetime.today() - timedelta(days=2)
        addon.versions.latest().update(nomination=earlier)
        addon.update(status=amo.STATUS_NOMINATED)
        eq_(addon.versions.latest().nomination.date(), earlier.date())



class TestBackupVersion(test_utils.TestCase):
    fixtures = ['addons/update']

    def setUp(self):
        self.version_1_2_0 = 105387
        self.addon = Addon.objects.get(pk=1865)
        set_user(None)

    def setup_new_version(self):
        for version in Version.objects.filter(pk__gte=self.version_1_2_0):
            appversion = version.apps.all()[0]
            appversion.min = AppVersion.objects.get(version='4.0b1')
            appversion.save()

    def test_no_backup_version(self):
        self.addon.update_version()
        eq_(self.addon.backup_version, None)
        eq_(self.addon.current_version.version, '1.2.2')

    def test_no_current_version(self):
        Version.objects.all().delete()
        self.addon.update(_current_version=None)
        eq_(self.addon.backup_version, None)
        eq_(self.addon.current_version, None)

    def test_has_backup_version(self):
        self.setup_new_version()
        assert self.addon.update_version()
        eq_(self.addon.backup_version.version, '1.1.3')
        eq_(self.addon.current_version.version, '1.2.2')

    def test_backup_version(self):
        self.setup_new_version()
        assert self.addon.update_version()
        eq_(self.addon.backup_version.version, '1.1.3')

    def test_firefox_versions(self):
        self.setup_new_version()
        assert self.addon.update_version()
        backup = self.addon.backup_version.compatible_apps[amo.FIREFOX]
        eq_(backup.max.version, '3.7a5pre')
        eq_(backup.min.version, '3.0.12')
        current = self.addon.current_version.compatible_apps[amo.FIREFOX]
        eq_(current.max.version, '4.0b8pre')
        eq_(current.min.version, '3.0.12')

    def test_version_signals(self):
        self.setup_new_version()
        version = self.addon.versions.all()[0]
        assert not self.addon.backup_version
        version.save()
        assert Addon.objects.get(pk=1865).backup_version


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


class TestFrozenAddons(test_utils.TestCase):

    def test_immediate_freeze(self):
        # Adding a FrozenAddon should immediately drop the addon's hotness.
        a = Addon.objects.create(type=1, hotness=22)
        FrozenAddon.objects.create(addon=a)
        eq_(Addon.objects.get(id=a.id).hotness, 0)
