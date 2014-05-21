from django import test

from jingo import env
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from addons.models import Addon
from tags.models import AddonTag, Tag
from tags.helpers import tag_link


xss = "<script>alert('xss')</script>"


def render(s, context={}):
    """Taken from jingo.tests.utils, previously jingo.tests.test_helpers."""
    t = env.from_string(s)
    return t.render(context)


class TestHelpers(test.TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'base/user_4043307',
                'tags/tags')

    def test_tag_list(self):
        addon = Addon.objects.get(id=3615)

        request = Mock()
        request.user = addon.authors.all()[0]
        request.groups = ()

        tags = addon.tags.not_blacklisted()

        ctx = {
            'APP': amo.FIREFOX,
            'LANG': 'en-us',
            'request': request,
            'addon': addon,
            'tags': tags}

        # no tags, no list
        s = render('{{ tag_list(addon) }}', ctx)
        self.assertEqual(s.strip(), "")

        s = render('{{ tag_list(addon, tags=tags) }}', ctx)
        assert s, "Non-empty tags must return tag list."
        doc = pq(s)
        eq_(doc('li').length, len(tags))

    def test_helper(self):
        addon = Addon.objects.get(pk=3615)
        tag = addon.tags.all()[0]
        tag.tag_text = xss
        tag.num_addons = 1
        tag.save()

        doc = pq(tag_link(tag, 1, 1))
        assert not doc('a')


def create_tags(addon, author, number):
    for x in range(0, number):
        tag = Tag.objects.create(tag_text='tag %s' % x, blacklisted=False)
        AddonTag.objects.create(tag=tag, addon=addon, user=author)
