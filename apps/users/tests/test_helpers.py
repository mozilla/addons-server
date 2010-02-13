from nose.tools import eq_

from users.helpers import emaillink, user_link
from users.models import UserProfile


def test_emaillink():
    email = 'me@example.com'
    obfuscated = unicode(emaillink(email))

    # remove junk
    m = re.match(r'<span class="emaillink">(.*?)<span class="i">null</span>(.*)'
                 '</span>', obfuscated)
    obfuscated = (''.join((m.group(1), m.group(2)))
                  .replace('&#x0040;', '@').replace('&#x002E;', '.'))[::-1]

    eq_(email, obfuscated)


def test_user_link():
    u = UserProfile(firstname='John', lastname='Connor', pk=1)
    eq_(user_link(u), """<a href="/users/1">John Connor</a>""")
