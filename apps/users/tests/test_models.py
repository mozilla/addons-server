from datetime import date
import hashlib

from django.contrib.auth.models import User
from django.core import mail
from django.utils import encoding

import test_utils
from nose.tools import eq_

import amo
from addons.models import Addon, AddonUser
from bandwagon.models import Collection
from reviews.models import Review
from users.models import UserProfile, get_hexdigest, BlacklistedUsername,\
                         BlacklistedEmailDomain


class TestUserProfile(test_utils.TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'users/test_backends',
                'base/apps',)

    def test_anonymize(self):
        u = User.objects.get(id='4043307').get_profile()
        eq_(u.email, 'jbalogh@mozilla.com')
        u.anonymize()
        x = UserProfile.objects.get(id='4043307')
        eq_(x.email, None)

    def test_delete(self):
        """Setting profile to delete should delete related User."""
        u = User.objects.get(id='4043307').get_profile()
        u.deleted = True
        u.save()
        eq_(len(User.objects.filter(id='4043307')), 0)

    def test_email_confirmation_code(self):
        u = User.objects.get(id='4043307').get_profile()
        u.confirmationcode = 'blah'
        u.email_confirmation_code()

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/confirm/%s' %
                                        (u.id, u.confirmationcode)) > 0

    def test_welcome_name(self):
        u1 = UserProfile(username='sc')
        u2 = UserProfile(username='sc', display_name="Sarah Connor")
        u3 = UserProfile()
        eq_(u1.welcome_name, 'sc')
        eq_(u2.welcome_name, 'Sarah Connor')
        eq_(u3.welcome_name, '')

    def test_empty_username(self):
        u = UserProfile.objects.create(email='yoyoyo@yo.yo', username='yoyo')
        assert u.user is None
        u.create_django_user()
        eq_(u.user.username, 'yoyoyo@yo.yo')

    def test_resetcode_expires(self):
        """
        For some reason resetcode is required, and we default it to
        '0000-00-00 00:00' in mysql, but that doesn't fly in Django since it's
        an invalid date.  If Django reads this from the db, it interprets this
        as resetcode_expires as None
        """

        u = UserProfile(username='jconnor', pk=2, resetcode_expires=None,
                        email='j.connor@sky.net')
        u.save()
        assert u.resetcode_expires

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile(id=1234, picture_type='image/png',
                        modified=date.today())
        u.picture_url.index('/userpics/0/1/1234.png?modified=')

        u = UserProfile(id=1234567890, picture_type='image/png',
                        modified=date.today())
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
        version = addon.get_current_version()
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


class TestPasswords(test_utils.TestCase):
    utf = u'\u0627\u0644\u062a\u0637\u0628'

    def test_invalid_old_password(self):
        u = UserProfile(password=self.utf)
        assert u.check_password(self.utf) is False

    def test_invalid_new_password(self):
        u = UserProfile()
        u.set_password(self.utf)
        assert u.check_password('wrong') is False

    def test_valid_old_password(self):
        hsh = hashlib.md5(encoding.smart_str(self.utf)).hexdigest()
        u = UserProfile(password=hsh)
        assert u.check_password(self.utf) is True
        # Make sure we updated the old password.
        algo, salt, hsh = u.password.split('$')
        eq_(algo, 'sha512')
        eq_(hsh, get_hexdigest(algo, salt, self.utf))

    def test_valid_new_password(self):
        u = UserProfile()
        u.set_password(self.utf)
        assert u.check_password(self.utf) is True


class TestBlacklistedUsername(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        eq_(BlacklistedUsername.blocked('IE6Fan'), True)
        eq_(BlacklistedUsername.blocked('testo'), False)


class TestBlacklistedEmailDomain(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def test_blocked(self):
        eq_(BlacklistedEmailDomain.blocked('mailinator.com'), True)
        assert not BlacklistedEmailDomain.blocked('mozilla.com')
