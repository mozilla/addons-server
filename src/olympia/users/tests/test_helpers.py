from olympia.users.models import UserProfile
from olympia.users.templatetags.jinja_helpers import user_link


def test_user_link():
    user = UserProfile(username='jconnor', display_name='John Connor', pk=1)
    assert user_link(user) == (
        f'<a href="{user.get_absolute_url()}" title="{user.name}">John Connor</a>'
    )

    # handle None gracefully
    assert user_link(None) == ''


def test_user_link_xss():
    user = UserProfile(
        username='jconnor', display_name='<script>alert(1)</script>', pk=1
    )
    html = '&lt;script&gt;alert(1)&lt;/script&gt;'
    assert user_link(user) == '<a href="{}" title="{}">{}</a>'.format(
        user.get_absolute_url(),
        html,
        html,
    )

    user = UserProfile(
        username='jconnor', display_name="""xss"'><iframe onload=alert(3)>""", pk=1
    )
    html = 'xss&#34;&#39;&gt;&lt;iframe onload=alert(3)&gt;'
    assert user_link(user) == '<a href="{}" title="{}">{}</a>'.format(
        user.get_absolute_url(),
        html,
        html,
    )


def test_user_link_unicode():
    """make sure helper won't choke on unicode input"""
    user = UserProfile(username='jmüller', display_name='Jürgen Müller')
    assert user_link(user) == (
        '<a href="%s" title="%s">Jürgen Müller</a>'
        % (user.get_absolute_url(), user.name)
    )

    user = UserProfile(display_name='\xe5\xaf\x92\xe6\x98\x9f')
    assert user_link(user) == (
        '<a href="%s" title="%s">%s</a>'
        % (user.get_absolute_url(), user.name, user.display_name)
    )
