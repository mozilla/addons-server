from nose.tools import eq_

from users.helpers import user_link
from users.models import UserProfile


def test_user_link():
    u = UserProfile(firstname='John', lastname='Connor', pk=1)
    eq_(user_link(u), """<a href="/users/1">John Connor</a>""")
