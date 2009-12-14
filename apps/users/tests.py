from nose.tools import eq_

from .helpers import user_link
from .models import UserProfile


def test_user_link():
    u = UserProfile(firstname='John', lastname='Connor', pk=1)
    eq_(user_link(u), """<a href="/users/1">John Connor</a>""")


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
    assert(u.resetcode_expires)
