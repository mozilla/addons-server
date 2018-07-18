from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia.amo.tests import BaseTestCase
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection
from olympia.bandwagon.templatetags.jinja_helpers import (
    barometer,
    user_collection_list,
)
from olympia.users.models import UserProfile


class TestHelpers(BaseTestCase):
    @patch(
        'olympia.bandwagon.templatetags.jinja_helpers.login_link',
        lambda c: 'https://login',
    )
    def test_barometer(self):
        self.client.get('/')
        collection = Collection(
            upvotes=1,
            slug='mccrackin',
            author=UserProfile(username='clouserw'),
        )
        # Mock logged out.
        c = {
            'request': Mock(
                path='yermom',
                GET=Mock(urlencode=lambda: ''),
                session={'fxa_state': 'foobar'},
            ),
            'user': Mock(),
            'settings': Mock(),
        }
        c['request'].user.is_authenticated.return_value = False
        doc = pq(barometer(c, collection))
        assert doc('form')[0].action == 'https://login'

        # Mock logged in.
        c['request'].user.votes.filter.return_value = [Mock(vote=1)]
        c['request'].user.is_authenticated.return_value = True
        barometer(c, collection)
        doc = pq(barometer(c, collection))
        assert doc('form')[0].action == (
            reverse('collections.vote', args=['clouserw', 'mccrackin', 'up'])
        )

    def test_user_collection_list(self):
        c1 = Collection(uuid='eb4e3cd8-5cf1-4832-86fb-a90fc6d3765c')
        c2 = Collection(
            uuid='61780943-e159-4206-8acd-0ae9f63f294c',
            nickname='my_collection',
        )
        heading = 'My Heading'
        response = unicode(user_collection_list([c1, c2], heading))

        # heading
        assert pq(response)('h3').text() == heading

        # both items
        # TODO reverse URLs
        assert c1.get_url_path() in response, 'Collection UUID link missing.'
        assert (
            c2.get_url_path() in response
        ), 'Collection nickname link missing.'

        # empty collection, empty response
        response = unicode(user_collection_list([], heading))
        assert not response, 'empty collection should not create a list'
