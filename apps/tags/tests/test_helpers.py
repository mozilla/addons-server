from datetime import datetime

from django import test

import jingo
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
from tags.models import Tag
from tags.helpers import tag_list


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


class TestHelpers(test.TestCase):
    fixtures = ['base/addons.json', 'tags/tags.json']

    def test_tag_list(self):
        addon = Addon.objects.get(id=3615)

        request = Mock()
        request.user = addon.authors.all()[0].create_django_user()

        tags = addon.tags.filter(blacklisted=False)
        dev_tags = tags.filter(addon_tags__user__in=addon.authors.all())
        user_tags = tags.exclude(addon_tags__user__in=addon.authors.all())

        ctx = {
            'APP': 'firefox',
            'LANG': 'en-us',
            'request': request,
            'addon': addon,
            'dev_tags': dev_tags,
            'user_tags': user_tags,
        }

        # initialize jingo
        jingo.load_helpers()
        cake_csrf_token = lambda: ''
        cake_csrf_token.__name__ = 'cake_csrf_token'
        jingo.register.function(cake_csrf_token)

        # no tags, no list
        s = render('{{ tag_list(addon) }}', ctx)
        assert not s, "Empty tags should not return tag list."

        # regular lists
        s = render('{{ tag_list(addon, dev_tags=dev_tags) }}', ctx)
        assert s, "Non-empty tags must return tag list."
        doc = pq(s)
        eq_(doc('li.developertag').length, len(dev_tags))
        eq_(doc('li').length, len(dev_tags))

        s = render('{{ tag_list(addon, user_tags=user_tags) }}', ctx)
        assert s, "Non-empty tags must return tag list."
        doc = pq(s)
        eq_(doc('li.usertag').length, len(user_tags))
        eq_(doc('li').length, len(user_tags))

        s = render("""{{ tag_list(addon, dev_tags=dev_tags,
                                  user_tags=user_tags) }}""", ctx)
        assert s, "Non-empty tags must return tag list."
        doc = pq(s)
        eq_(doc('li.usertag').length, len(user_tags))
        eq_(doc('li.developertag').length, len(dev_tags))
        eq_(doc('li').length, len(user_tags)+len(dev_tags))
