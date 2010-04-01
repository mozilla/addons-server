from datetime import date
import hashlib

from django import test
from django.contrib.auth.models import User
from django.core import mail

from nose.tools import eq_

from addons.models import Addon
from reviews.models import Review
from users.models import UserProfile, get_hexdigest


class TestUserProfile(test.TestCase):
    fixtures = ['base/addons.json', 'users/test_backends']

    def test_anonymize(self):
        u = User.objects.get(id='4043307').get_profile()
        eq_(u.email, 'jbalogh@mozilla.com')
        u.anonymize()
        x = User.objects.get(id='4043307').get_profile()
        eq_(x.email, "")

    def test_display_name_nickname(self):
        u = UserProfile(nickname='Terminator', pk=1)
        eq_(u.display_name, 'Terminator')

    def test_email_confirmation_code(self):
        u = User.objects.get(id='4043307').get_profile()
        u.confirmationcode = 'blah'
        u.email_confirmation_code()

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/confirm/%s' %
                                        (u.id, u.confirmationcode)) > 0

    def test_welcome_name(self):
        u1 = UserProfile(lastname='Connor')
        u2 = UserProfile(firstname='Sarah', nickname='sc', lastname='Connor')
        u3 = UserProfile(nickname='sc', lastname='Connor')
        u4 = UserProfile()
        eq_(u1.welcome_name, 'Connor')
        eq_(u2.welcome_name, 'Sarah')
        eq_(u3.welcome_name, 'sc')
        eq_(u4.welcome_name, '')

    def test_name(self):
        u1 = UserProfile(firstname='Sarah', lastname='Connor')
        u2 = UserProfile(firstname='Sarah')
        eq_(u1.name, 'Sarah Connor')
        eq_(u2.name, 'Sarah')  # No trailing space

    def test_empty_nickname(self):
        u = UserProfile.objects.create(email='yoyoyo@yo.yo', nickname='yoyo')
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

        u = UserProfile(lastname='Connor', pk=2, resetcode_expires=None,
                        nickname='jconnor', email='j.connor@sky.net')
        u.save()
        assert u.resetcode_expires

    def test_picture_url(self):
        """
        Test for a preview URL if image is set, or default image otherwise.
        """
        u = UserProfile(id=1234, picture_type='image/png',
                        modified=date.today())
        u.picture_url.index('/userpics/0/1/1234.jpg?modified=')

        u = UserProfile(id=1234567890, picture_type='image/png',
                        modified=date.today())
        u.picture_url.index('/userpics/1234/1234567/1234567890.jpg?modified=')

        u = UserProfile(id=1234, picture_type=None)
        assert u.picture_url.endswith('/anon_user.png')

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=2519)
        version = addon.current_version
        new_review = Review(version=version, user=u, rating=2, body='hello')
        new_review.save()
        new_reply = Review(version=version, user=u, reply_to=new_review,
                           body='my reply')
        new_reply.save()

        review_list = [ r.pk for r in u.reviews ]

        eq_(len(review_list), 1)
        assert new_review.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')


class TestPasswords(test.TestCase):

    def test_invalid_old_password(self):
        u = UserProfile(password='sekrit')
        assert u.check_password('sekrit') is False

    def test_invalid_new_password(self):
        u = UserProfile()
        u.set_password('sekrit')
        assert u.check_password('wrong') is False

    def test_valid_old_password(self):
        hsh = hashlib.md5('sekrit').hexdigest()
        u = UserProfile(password=hsh)
        assert u.check_password('sekrit') is True
        # Make sure we updated the old password.
        algo, salt, hsh = u.password.split('$')
        eq_(algo, 'sha512')
        eq_(hsh, get_hexdigest(algo, salt, 'sekrit'))

    def test_valid_new_password(self):
        u = UserProfile()
        u.set_password('sekrit')
        assert u.check_password('sekrit') is True
