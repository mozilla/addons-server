# -*- coding: utf-8 -*-
import re

from nose.tools import eq_

from amo.urlresolvers import reverse
from users.helpers import emaillink, user_link, users_list
from users.models import UserProfile


def test_emaillink():
    email = 'me@example.com'
    obfuscated = unicode(emaillink(email))

    # remove junk
    m = re.match(r'<span class="emaillink">(.*?)<span class="i">null</span>'
                 '(.*)</span>', obfuscated)
    obfuscated = (''.join((m.group(1), m.group(2)))
                  .replace('&#x0040;', '@').replace('&#x002E;', '.'))[::-1]

    eq_(email, obfuscated)


def test_user_link():
    u = UserProfile(firstname='John', lastname='Connor', pk=1)
    eq_(user_link(u), '<a href="%s">John Connor</a>' %
        reverse('users.profile', args=[1]))


def test_users_list():
    u1 = UserProfile(firstname='John', lastname='Connor', pk=1)
    u2 = UserProfile(firstname='Sarah', lastname='Connor', pk=2)
    eq_(users_list([u1, u2]), ', '.join((user_link(u1), user_link(u2))))


def test_user_link_unicode():
    """make sure helper won't choke on unicode input"""
    u = UserProfile(firstname=u'Jürgen', lastname=u'Müller', pk=1)
    eq_(user_link(u), u'<a href="%s">Jürgen Müller</a>' %
        reverse('users.profile', args=[1]))
