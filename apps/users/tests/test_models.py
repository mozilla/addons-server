# -*- coding: utf-8 -*-
import datetime
import hashlib
from base64 import encodestring
from urlparse import urlparse

from django import forms
from django.conf import settings
from django.contrib.auth.hashers import (is_password_usable, check_password,
                                         make_password, identify_hasher)
from django.core import mail
from django.utils import encoding, translation

from mock import patch
from nose.tools import eq_
from test_utils import trans_eq

import amo
import amo.tests
from access.models import Group, GroupUser
from addons.models import Addon, AddonUser
from amo.signals import _connect, _disconnect
from bandwagon.models import Collection
from reviews.models import Review
from translations.models import Translation
from users.models import (BlacklistedEmailDomain, BlacklistedPassword,
                          BlacklistedName, get_hexdigest, UserEmailField,
                          UserProfile)
from users.utils import find_users


class TestUserProfile(amo.tests.TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'base/user_4043307',
                'users/test_backends')

    def test_anonymize(self):
        u = UserProfile.objects.get(id='4043307')
        eq_(u.email, 'jbalogh@mozilla.com')
        u.anonymize()
        x = UserProfile.objects.get(id='4043307')
        eq_(x.email, None)

    def test_email_confirmation_code(self):
        u = UserProfile.objects.get(id='4043307')
        u.confirmationcode = 'blah'
        u.email_confirmation_code()

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject, 'Please confirm your email address')
        assert mail.outbox[0].body.find('%s/confirm/%s' %
                                        (u.id, u.confirmationcode)) > 0

    @patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_email_confirmation_code_even_with_fake_email(self):
        u = UserProfile.objects.get(id='4043307')
        u.confirmationcode = 'blah'
        u.email_confirmation_code()

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject, 'Please confirm your email address')

    def test_welcome_name(self):
        u1 = UserProfile(username='sc')
        u2 = UserProfile(username='sc', display_name="Sarah Connor")
        u3 = UserProfile()
        eq_(u1.welcome_name, 'sc')
        eq_(u2.welcome_name, 'Sarah Connor')
        eq_(u3.welcome_name, '')

    def test_add_admin_powers(self):
        u = UserProfile.objects.get(username='jbalogh')

        assert not u.is_staff
        assert not u.is_superuser
        GroupUser.objects.create(group=Group.objects.get(name='Admins'),
                                 user=u)
        assert u.is_staff
        assert u.is_superuser

    def test_dont_add_admin_powers(self):
        Group.objects.create(name='API', rules='API.Users:*')
        u = UserProfile.objects.get(username='jbalogh')

        GroupUser.objects.create(group=Group.objects.get(name='API'),
                                 user=u)
        assert not u.is_staff
        assert not u.is_superuser

    def test_remove_admin_powers(self):
        Group.objects.create(name='Admins', rules='*:*')
        u = UserProfile.objects.get(username='jbalogh')
        g = GroupUser.objects.create(group=Group.objects.filter(name='Admins')[0],
                                     user=u)
        g.delete()
        assert not u.is_staff
        assert not u.is_superuser

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile(id=1234, picture_type='image/png',
                        modified=datetime.date.today())
        u.picture_url.index('/userpics/0/1/1234.png?modified=')

        u = UserProfile(id=1234567890, picture_type='image/png',
                        modified=datetime.date.today())
        u.picture_url.index('/userpics/1234/1234567/1234567890.png?modified=')

        u = UserProfile(id=1234, picture_type=None)
        assert u.picture_url.endswith('/anon_user.png')

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=2519)
        version = addon.get_version()
        new_review = Review(version=version, user=u, rating=2, body='hello',
                            addon=addon)
        new_review.save()
        new_reply = Review(version=version, user=u, reply_to=new_review,
                           addon=addon, body='my reply')
        new_reply.save()

        review_list = [r.pk for r in u.reviews]

        eq_(len(review_list), 1)
        assert new_review.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')

    def test_addons_listed(self):
        """Make sure we're returning distinct add-ons."""
        AddonUser.objects.create(addon_id=3615, user_id=2519, listed=True)
        u = UserProfile.objects.get(id=2519)
        addons = u.addons_listed.values_list('id', flat=True)
        eq_(sorted(addons), [3615])

    def test_addons_not_listed(self):
        """Make sure user is not listed when another is."""
        AddonUser.objects.create(addon_id=3615, user_id=2519, listed=False)
        AddonUser.objects.create(addon_id=3615, user_id=4043307, listed=True)
        u = UserProfile.objects.get(id=2519)
        addons = u.addons_listed.values_list('id', flat=True)
        assert 3615 not in addons

    def test_my_addons(self):
        """Test helper method to get N addons."""
        addon1 = Addon.objects.create(name='test-1', type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon_id=addon1.id, user_id=2519, listed=True)
        addon2 = Addon.objects.create(name='test-2', type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(addon_id=addon2.id, user_id=2519, listed=True)
        addons = UserProfile.objects.get(id=2519).my_addons()
        eq_(sorted(a.name for a in addons), [addon1.name, addon2.name])

    def test_mobile_collection(self):
        u = UserProfile.objects.get(id='4043307')
        assert not Collection.objects.filter(author=u)

        c = u.mobile_collection()
        eq_(c.type, amo.COLLECTION_MOBILE)
        eq_(c.slug, 'mobile')

    def test_favorites_collection(self):
        u = UserProfile.objects.get(id='4043307')
        assert not Collection.objects.filter(author=u)

        c = u.favorites_collection()
        eq_(c.type, amo.COLLECTION_FAVORITES)
        eq_(c.slug, 'favorites')

    def test_get_url_path(self):
        eq_(UserProfile(username='yolo').get_url_path(),
            '/en-US/firefox/user/yolo/')
        eq_(UserProfile(username='yolo', id=1).get_url_path(),
            '/en-US/firefox/user/yolo/')
        eq_(UserProfile(id=1).get_url_path(),
            '/en-US/firefox/user/1/')
        eq_(UserProfile(username='<yolo>', id=1).get_url_path(),
            '/en-US/firefox/user/1/')

    @patch.object(settings, 'LANGUAGE_CODE', 'en-US')
    def test_activate_locale(self):
        eq_(translation.get_language(), 'en-us')
        with UserProfile(username='yolo').activate_lang():
            eq_(translation.get_language(), 'en-us')

        with UserProfile(username='yolo', lang='fr').activate_lang():
            eq_(translation.get_language(), 'fr')

    def test_remove_locale(self):
        u = UserProfile.objects.create()
        u.bio = {'en-US': 'my bio', 'fr': 'ma bio'}
        u.save()
        u.remove_locale('fr')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        eq_(sorted(qs.filter(id=u.bio_id)), ['en-US'])

    def test_get_fallback(self):
        """Return the translation for the locale fallback."""
        user = UserProfile.objects.create(
            lang='fr', bio={'en-US': 'my bio', 'fr': 'ma bio'})
        trans_eq(user.bio, 'my bio', 'en-US')  # Uses current locale.

        with self.activate(locale='de'):
            user = UserProfile.objects.get(pk=user.pk)  # Reload.
            trans_eq(user.bio, 'ma bio', 'fr')  # Uses the default fallback.


class TestPasswords(amo.tests.TestCase):
    utf = u'\u0627\u0644\u062a\u0637\u0628'
    bytes_ = '\xb1\x98og\x88\x87\x08q'

    def test_invalid_old_password(self):
        u = UserProfile(password=self.utf)
        assert u.check_password(self.utf) is False
        assert u.has_usable_password() is True

    def test_invalid_new_password(self):
        u = UserProfile()
        u.set_password(self.utf)
        assert u.check_password('wrong') is False
        assert u.has_usable_password() is True

    def test_valid_old_password(self):
        hsh = hashlib.md5(encoding.smart_str(self.utf)).hexdigest()
        u = UserProfile(password=hsh)
        assert u.check_password(self.utf) is True
        # Make sure we updated the old password.
        algo, salt, hsh = u.password.split('$')
        eq_(algo, 'sha512')
        eq_(hsh, get_hexdigest(algo, salt, self.utf))
        assert u.has_usable_password() is True

    def test_valid_new_password(self):
        u = UserProfile()
        u.set_password(self.utf)
        assert u.check_password(self.utf) is True
        assert u.has_usable_password() is True

    def test_persona_sha512_md5(self):
        md5 = hashlib.md5('password').hexdigest()
        hsh = hashlib.sha512(self.bytes_ + md5).hexdigest()
        u = UserProfile(password='sha512+MD5$%s$%s' %
                        (self.bytes_, hsh))
        assert u.check_password('password') is True
        assert u.has_usable_password() is True

    def test_persona_sha512_base64(self):
        hsh = hashlib.sha512(self.bytes_ + 'password').hexdigest()
        u = UserProfile(password='sha512+base64$%s$%s' %
                        (encodestring(self.bytes_), hsh))
        assert u.check_password('password') is True
        assert u.has_usable_password() is True

    def test_persona_sha512_base64_maybe_utf8(self):
        hsh = hashlib.sha512(self.bytes_ + self.utf.encode('utf8')).hexdigest()
        u = UserProfile(password='sha512+base64$%s$%s' %
                        (encodestring(self.bytes_), hsh))
        assert u.check_password(self.utf) is True
        assert u.has_usable_password() is True

    def test_persona_sha512_base64_maybe_latin1(self):
        passwd = u'fo\xf3'
        hsh = hashlib.sha512(self.bytes_ + passwd.encode('latin1')).hexdigest()
        u = UserProfile(password='sha512+base64$%s$%s' %
                        (encodestring(self.bytes_), hsh))
        assert u.check_password(passwd) is True
        assert u.has_usable_password() is True

    def test_persona_sha512_base64_maybe_not_latin1(self):
        passwd = u'fo\xf3'
        hsh = hashlib.sha512(self.bytes_ + passwd.encode('latin1')).hexdigest()
        u = UserProfile(password='sha512+base64$%s$%s' %
                        (encodestring(self.bytes_), hsh))
        assert u.check_password(self.utf) is False
        assert u.has_usable_password() is True

    def test_persona_sha512_md5_base64(self):
        md5 = hashlib.md5('password').hexdigest()
        hsh = hashlib.sha512(self.bytes_ + md5).hexdigest()
        u = UserProfile(password='sha512+MD5+base64$%s$%s' %
                        (encodestring(self.bytes_), hsh))
        assert u.check_password('password') is True
        assert u.has_usable_password() is True

    def test_browserid_password(self):
        u = UserProfile(password=self.utf, source=amo.LOGIN_SOURCE_UNKNOWN)
        assert not u.check_password('foo')
        assert u.has_usable_password() is True

    @patch('access.acl.action_allowed_user')
    def test_needs_tougher_password(self, action_allowed_user):
        for source in amo.LOGIN_SOURCE_BROWSERIDS:
            u = UserProfile(password=self.utf, source=source)
            assert not u.needs_tougher_password

        u = UserProfile(password=self.utf, source=amo.LOGIN_SOURCE_UNKNOWN)
        assert u.needs_tougher_password

    def test_sha512(self):
        encoded = make_password('lètmein', 'seasalt', 'sha512')
        self.assertEqual(
            encoded,
            'sha512$seasalt$16bf4502ffdfce9551b90319d06674e6faa3e174144123d'
            '392d94470ebf0aa77096b871f9e84f60ed2bac2f10f755368b068e52547e04'
            '35fef8b4f6ca237d7d8')
        self.assertTrue(is_password_usable(encoded))
        self.assertTrue(check_password('lètmein', encoded))
        self.assertFalse(check_password('lètmeinz', encoded))
        self.assertEqual(identify_hasher(encoded).algorithm, "sha512")
        # Blank passwords
        blank_encoded = make_password('', 'seasalt', 'sha512')
        self.assertTrue(blank_encoded.startswith('sha512$'))
        self.assertTrue(is_password_usable(blank_encoded))
        self.assertTrue(check_password('', blank_encoded))
        self.assertFalse(check_password(' ', blank_encoded))

    def test_empty_password(self):
        profile = UserProfile(password=None)
        assert profile.has_usable_password() is False
        profile = UserProfile(password='')
        assert profile.has_usable_password() is False


class TestBlacklistedName(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        eq_(BlacklistedName.blocked('IE6Fan'), True)
        eq_(BlacklistedName.blocked('IE6fantastic'), True)
        eq_(BlacklistedName.blocked('IE6'), False)
        eq_(BlacklistedName.blocked('testo'), False)


class TestBlacklistedEmailDomain(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        eq_(BlacklistedEmailDomain.blocked('mailinator.com'), True)
        assert not BlacklistedEmailDomain.blocked('mozilla.com')


class TestFlushURLs(amo.tests.TestCase):
    fixtures = ['base/user_2519']

    def setUp(self):
        _connect()

    def tearDown(self):
        _disconnect()

    @patch('amo.tasks.flush_front_end_cache_urls.apply_async')
    def test_flush(self, flush):
        user = UserProfile.objects.get(pk=2519)
        user.save()
        assert user.picture_url in flush.call_args[1]['args'][0]
        assert urlparse(user.picture_url).query.find('modified') > -1


class TestUserEmailField(amo.tests.TestCase):
    fixtures = ['base/user_2519']

    def test_success(self):
        user = UserProfile.objects.get(pk=2519)
        eq_(UserEmailField().clean(user.email), user)

    def test_failure(self):
        with self.assertRaises(forms.ValidationError):
            UserEmailField().clean('xxx')

    def test_empty_email(self):
        UserProfile.objects.create(email='')
        with self.assertRaises(forms.ValidationError) as e:
            UserEmailField().clean('')
        eq_(e.exception.messages[0], 'This field is required.')


class TestBlacklistedPassword(amo.tests.TestCase):

    def test_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        assert BlacklistedPassword.blocked('password')
        assert not BlacklistedPassword.blocked('passw0rd')


class TestUserHistory(amo.tests.TestCase):

    def test_user_history(self):
        user = UserProfile.objects.create(email='foo@bar.com')
        eq_(user.history.count(), 0)
        user.update(email='foopy@barby.com')
        eq_(user.history.count(), 1)
        user.update(email='foopy@barby.com')
        eq_(user.history.count(), 1)

    def test_user_find(self):
        user = UserProfile.objects.create(email='luke@jedi.com')
        # Checks that you can have multiple copies of the same email and
        # that we only get distinct results back.
        user.update(email='dark@sith.com')
        user.update(email='luke@jedi.com')
        user.update(email='dark@sith.com')
        eq_([user], list(find_users('luke@jedi.com')))
        eq_([user], list(find_users('dark@sith.com')))

    def test_user_find_multiple(self):
        user_1 = UserProfile.objects.create(username='user_1',
                                            email='luke@jedi.com')
        user_1.update(email='dark@sith.com')
        user_2 = UserProfile.objects.create(username='user_2',
                                            email='luke@jedi.com')
        eq_([user_1, user_2], list(find_users('luke@jedi.com')))


class TestUserManager(amo.tests.TestCase):
    fixtures = ('users/test_backends', )

    def test_create_user(self):
        user = UserProfile.objects.create_user("test", "test@test.com", 'xxx')
        assert user.pk is not None

    def test_create_superuser(self):
        user = UserProfile.objects.create_superuser(
            "test",
            "test@test.com",
            'xxx'
        )
        assert user.pk is not None
        Group.objects.get(name="Admins") in user.groups.all()
        assert user.is_staff
        assert user.is_superuser
