from mock import Mock
from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon


def render(s, context=None):
    """Taken from jingo.tests.utils, previously jingo.tests.test_helpers."""
    if context is None:
        context = {}
    t = amo.utils.from_string(s)
    return t.render(context)


class TestHelpers(amo.tests.BaseTestCase):
    fixtures = (
        'base/addon_3615',
        'base/user_2519',
        'base/user_4043307',
        'tags/tags',
    )

    def test_tag_list(self):
        addon = Addon.objects.get(id=3615)

        request = Mock()
        request.user = addon.authors.all()[0]

        tags = addon.tags.not_denied()

        ctx = {
            'APP': amo.FIREFOX,
            'LANG': 'en-us',
            'request': request,
            'addon': addon,
            'tags': tags,
        }

        # no tags, no list
        s = render('{{ tag_list(addon) }}', ctx)
        assert s.strip() == ""

        s = render('{{ tag_list(addon, tags=tags) }}', ctx)
        assert s, "Non-empty tags must return tag list."
        doc = pq(s)
        assert doc('li').length == len(tags)
