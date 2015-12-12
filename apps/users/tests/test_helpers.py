# -*- coding: utf-8 -*-
import re

import pytest
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
from addons.tests.test_views import TestPersonas
import amo
import amo.tests
from users.helpers import (addon_users_list, emaillink, user_data, user_link,
                           users_list)
from users.models import UserProfile


pytestmark = pytest.mark.django_db


def test_emaillink():
    email = 'me@example.com'
    obfuscated = unicode(emaillink(email))

    # remove junk
    m = re.match(r'<a href="#"><span class="emaillink">(.*?)'
                 r'<span class="i">null</span>(.*)</span></a>'
                 r'<span class="emaillink js-hidden">(.*?)'
                 r'<span class="i">null</span>(.*)</span>', obfuscated)
    obfuscated = (''.join((m.group(1), m.group(2)))
                  .replace('&#x0040;', '@').replace('&#x002E;', '.'))[::-1]
    assert email == obfuscated

    title = 'E-mail your question'
    obfuscated = unicode(emaillink(email, title))
    m = re.match(r'<a href="#">(.*)</a>'
                 r'<span class="emaillink js-hidden">(.*?)'
                 r'<span class="i">null</span>(.*)</span>', obfuscated)
    assert title == m.group(1)
    obfuscated = (''.join((m.group(2), m.group(3)))
                  .replace('&#x0040;', '@').replace('&#x002E;', '.'))[::-1]
    assert email == obfuscated


def test_user_link():
    u = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    assert user_link(u) == '<a href="%s" title="%s">John Connor</a>' % (u.get_url_path(), u.name)
    assert user_link(None) == ''


def test_user_link_xss():
    u = UserProfile(username='jconnor',
                    display_name='<script>alert(1)</script>', pk=1)
    html = "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert user_link(u) == '<a href="%s" title="%s">%s</a>' % (u.get_url_path(), html, html)

    u = UserProfile(username='jconnor',
                    display_name="""xss"'><iframe onload=alert(3)>""", pk=1)
    html = """xss&#34;&#39;&gt;&lt;iframe onload=alert(3)&gt;"""
    assert user_link(u) == '<a href="%s" title="%s">%s</a>' % (u.get_url_path(), html, html)


def test_users_list():
    u1 = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    u2 = UserProfile(username='sconnor', display_name='Sarah Connor', pk=2)
    assert users_list([u1, u2]) == ', '.join((user_link(u1), user_link(u2)))
    assert user_link(None) == ''


def test_short_users_list():
    """Test the option to shortened the users list to a certain size."""
    # short list with 'others'
    u1 = UserProfile(username='oscar', display_name='Oscar the Grouch', pk=1)
    u2 = UserProfile(username='grover', display_name='Grover', pk=2)
    u3 = UserProfile(username='cookies!', display_name='Cookie Monster', pk=3)
    shortlist = users_list([u1, u2, u3], size=2)
    assert shortlist == ', '.join((user_link(u1), user_link(u2))) + ', others'


def test_users_list_truncate_display_name():
    u = UserProfile(username='oscar',
                    display_name='Some Very Long Display Name', pk=1)
    truncated_list = users_list([u], None, 10)
    assert truncated_list == u'<a href="%s" title="%s">Some Very...</a>' % (u.get_url_path(), u.name)


def test_user_link_unicode():
    """make sure helper won't choke on unicode input"""
    u = UserProfile(username=u'jmüller', display_name=u'Jürgen Müller', pk=1)
    assert user_link(u) == u'<a href="%s" title="%s">Jürgen Müller</a>' % ( u.get_url_path(), u.name)

    u = UserProfile(username='\xe5\xaf\x92\xe6\x98\x9f', pk=1)
    assert user_link(u) == u'<a href="%s" title="%s">%s</a>' % (u.get_url_path(), u.name, u.username)


class TestAddonUsersList(TestPersonas, amo.tests.TestCase):

    def setUp(self):
        super(TestAddonUsersList, self).setUp()
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.create_addon_user(self.addon)

    def test_by(self):
        """Test that the by... bit works."""
        content = addon_users_list({'amo': amo}, self.addon)
        assert pq(content).text() == 'by %s' % self.addon.authors.all()[0].name


def test_user_data():
    u = user_data(UserProfile(username='foo', pk=1))
    assert u['anonymous'] is False
