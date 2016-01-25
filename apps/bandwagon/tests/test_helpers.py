from mock import Mock
from pyquery import PyQuery as pq
import jingo

from amo.tests import BaseTestCase
from amo.urlresolvers import reverse
from bandwagon.helpers import (barometer, user_collection_list)
from bandwagon.models import Collection
from users.models import UserProfile


class TestHelpers(BaseTestCase):

    def test_barometer(self):
        self.client.get('/')
        jingo.load_helpers()
        collection = Collection(upvotes=1, slug='mccrackin',
                                author=UserProfile(username='clouserw'))
        # Mock logged out.
        c = {
            'request': Mock(path='yermom', GET=Mock(urlencode=lambda: '')),
            'user': Mock(),
            'settings': Mock()
        }
        c['request'].user.is_authenticated.return_value = False
        doc = pq(barometer(c, collection))
        assert doc('form')[0].action == '/en-US/firefox/users/login?to=yermom'

        # Mock logged in.
        c['request'].user.votes.filter.return_value = [Mock(vote=1)]
        c['request'].user.is_authenticated.return_value = True
        barometer(c, collection)
        doc = pq(barometer(c, collection))
        assert doc('form')[0].action == reverse('collections.vote', args=['clouserw', 'mccrackin', 'up'])

    def test_user_collection_list(self):
        c1 = Collection(uuid='eb4e3cd8-5cf1-4832-86fb-a90fc6d3765c')
        c2 = Collection(uuid='61780943-e159-4206-8acd-0ae9f63f294c',
                        nickname='my_collection')
        heading = 'My Heading'
        response = unicode(user_collection_list([c1, c2], heading))
        assert pq(response)('h3').text() == heading

        # both items
        # TODO reverse URLs
        assert c1.get_url_path() in response, 'Collection UUID link missing.'
        assert c2.get_url_path() in response, (
            'Collection nickname link missing.')

        # empty collection, empty response
        response = unicode(user_collection_list([], heading))
        assert not response, 'empty collection should not create a list'
