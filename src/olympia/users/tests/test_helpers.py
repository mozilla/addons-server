# -*- coding: utf-8 -*-
import pytest

from olympia.users.models import UserProfile
from olympia.users.templatetags.jinja_helpers import user_link, users_list


pytestmark = pytest.mark.django_db


def test_user_link():
    u = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    assert user_link(u) == (
        '<a href="%s" title="%s">John Connor</a>' % (u.get_url_path(),
                                                     u.name))

    # handle None gracefully
    assert user_link(None) == ''


def test_user_link_xss():
    u = UserProfile(username='jconnor',
                    display_name='<script>alert(1)</script>', pk=1)
    html = "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert user_link(u) == '<a href="%s" title="%s">%s</a>' % (
        u.get_url_path(), html, html)

    u = UserProfile(username='jconnor',
                    display_name="""xss"'><iframe onload=alert(3)>""", pk=1)
    html = """xss&#34;&#39;&gt;&lt;iframe onload=alert(3)&gt;"""
    assert user_link(u) == '<a href="%s" title="%s">%s</a>' % (
        u.get_url_path(), html, html)


def test_users_list():
    u1 = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    u2 = UserProfile(username='sconnor', display_name='Sarah Connor', pk=2)
    assert users_list([u1, u2]) == ', '.join((user_link(u1), user_link(u2)))

    # handle None gracefully
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
    assert truncated_list == (
        u'<a href="%s" title="%s">Some Very...</a>' % (u.get_url_path(),
                                                       u.name))


def test_user_link_unicode():
    """make sure helper won't choke on unicode input"""
    u = UserProfile.objects.create(
        username=u'jmüller', display_name=u'Jürgen Müller')
    assert user_link(u) == (
        u'<a href="%s" title="%s">Jürgen Müller</a>' % (
            u.get_url_path(), u.name))

    u = UserProfile.objects.create(display_name=u'\xe5\xaf\x92\xe6\x98\x9f')
    assert user_link(u) == (
        u'<a href="%s" title="%s">%s</a>' % (u.get_url_path(), u.name,
                                             u.display_name))
