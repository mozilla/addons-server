import hashlib

from django import test

from nose.tools import eq_

from users.models import UserProfile, get_hexdigest


def test_display_name_nickname():
    u = UserProfile(nickname='Terminator', pk=1)
    eq_(u.display_name, 'Terminator')


def test_welcome_name():
    u1 = UserProfile(lastname='Connor', pk=1)
    u2 = UserProfile(firstname='Sarah', nickname='sc', lastname='Connor', pk=1)
    u3 = UserProfile(nickname='sc', lastname='Connor', pk=1)
    u4 = UserProfile(pk=1)
    eq_(u1.welcome_name, 'Connor')
    eq_(u2.welcome_name, 'Sarah')
    eq_(u3.welcome_name, 'sc')
    eq_(u4.welcome_name, '')


def test_resetcode_expires():
    """
    For some reasone resetcode is required, and we default it to
    '0000-00-00 00:00' in mysql, but that doesn't fly in Django since it's an
    invalid date.  If Django reads this from the db, it interprets this as
    resetcode_expires as None
    """

    u = UserProfile(lastname='Connor', pk=2, resetcode_expires=None,
                    email='j.connor@sky.net')
    u.save()
    assert u.resetcode_expires


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
