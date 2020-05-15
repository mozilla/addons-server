# -*- coding: utf-8 -*-
import pytest

from olympia.users.models import UserProfile
from olympia.users.templatetags.jinja_helpers import user_link, users_list


pytestmark = pytest.mark.django_db


def test_user_link():
    user = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    assert user_link(user) == (
        '<a href="%s" title="%s">John Connor</a>' % (user.get_absolute_url(),
                                                     user.name))

    # handle None gracefully
    assert user_link(None) == ''


def test_user_link_xss():
    user = UserProfile(username='jconnor',
                       display_name='<script>alert(1)</script>', pk=1)
    html = '&lt;script&gt;alert(1)&lt;/script&gt;'
    assert user_link(user) == '<a href="%s" title="%s">%s</a>' % (
        user.get_absolute_url(), html, html)

    user = UserProfile(username='jconnor',
                       display_name="""xss"'><iframe onload=alert(3)>""", pk=1)
    html = """xss&#34;&#39;&gt;&lt;iframe onload=alert(3)&gt;"""
    assert user_link(user) == '<a href="%s" title="%s">%s</a>' % (
        user.get_absolute_url(), html, html)


def test_users_list():
    user1 = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    user2 = UserProfile(username='sconnor', display_name='Sarah Connor', pk=2)
    assert users_list([user1, user2]) == (
        ', '.join((user_link(user1), user_link(user2)))
    )

    # handle None gracefully
    assert user_link(None) == ''


def test_short_users_list():
    """Test the option to shortened the users list to a certain size."""
    # short list with 'others'
    user1 = UserProfile(
        username='oscar', display_name='Oscar the Grouch', pk=1)
    user2 = UserProfile(
        username='grover', display_name='Grover', pk=2)
    user3 = UserProfile(
        username='cookies!', display_name='Cookie Monster', pk=3)
    shortlist = users_list([user1, user2, user3], size=2)
    assert shortlist == (
        ', '.join((user_link(user1), user_link(user2))) + ', others'
    )


def test_users_list_truncate_display_name():
    user = UserProfile(username='oscar',
                       display_name='Some Very Long Display Name', pk=1)
    truncated_list = users_list([user], None, 10)
    assert truncated_list == (
        '<a href="%s" title="%s">Some Very...</a>' % (user.get_absolute_url(),
                                                      user.name))


def test_user_link_unicode():
    """make sure helper won't choke on unicode input"""
    user = UserProfile.objects.create(
        username='jmüller', display_name='Jürgen Müller')
    assert user_link(user) == (
        '<a href="%s" title="%s">Jürgen Müller</a>' % (
            user.get_absolute_url(), user.name))

    user = UserProfile.objects.create(display_name='\xe5\xaf\x92\xe6\x98\x9f')
    assert user_link(user) == (
        '<a href="%s" title="%s">%s</a>' % (user.get_absolute_url(), user.name,
                                            user.display_name))
