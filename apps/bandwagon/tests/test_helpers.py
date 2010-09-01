from django import test

from nose.tools import eq_
from mock import Mock
from pyquery import PyQuery as pq
import jingo

from amo.urlresolvers import reverse
from bandwagon.helpers import (user_collection_list, barometer,
                               collection_favorite)
from bandwagon.models import Collection
from cake.urlresolvers import remora_url
from users.models import UserProfile


class TestHelpers(test.TestCase):

    fixtures = ('base/apps',
                'base/users',
                'base/addon_3615',
                'base/collections',
                'users/test_backends',
                )

    def setUp(self):
        self.client.get('/')
        self.user = UserProfile.objects.create(username='uniq', email='uniq')

    def test_collection_favorite(self):
        c = {}
        c['request'] = Mock()
        c['request'].amo_user = self.user
        collection = Collection.objects.get(pk=80)

        # Not subscribed yet.
        doc = pq(collection_favorite(c, collection))
        eq_(doc('button').text(), u'Add to Favorites')

        # Subscribed.
        collection.following.create(user=self.user)
        doc = pq(collection_favorite(c, collection))
        eq_(doc('button').text(), u'Remove from Favorites')

    def test_barometer(self):
        jingo.load_helpers()
        collection = Collection.objects.get(pk=80)
        collection.upvotes = 1
        # Mock logged out.
        c = dict(request=Mock(), user=Mock(), LANG='en-US', APP='firefox')
        c['request'].path = 'yermom'
        c['request'].GET.urlencode = lambda: ''
        c['request'].user.is_authenticated = lambda: False
        doc = pq(barometer(c, collection))
        eq_(doc('form')[0].action, '/en-US/firefox/users/login?to=yermom')

        # Mock logged in.
        vote = Mock()
        vote.vote = 1
        c['request'].amo_user.votes.filter.return_value = [vote]
        c['request'].user.is_authenticated = lambda: True
        barometer(c, collection)
        doc = pq(barometer(c, collection))
        eq_(doc('form')[0].action,
            reverse('collections.vote', args=['clouserw', 'mccrackin', 'up']))

    def test_user_collection_list(self):
        c1 = Collection.objects.create(author=self.user,
            uuid='eb4e3cd8-5cf1-4832-86fb-a90fc6d3765c')
        c2 = Collection.objects.create(author=self.user,
            uuid='61780943-e159-4206-8acd-0ae9f63f294c',
            nickname='my_collection')
        heading = 'My Heading'
        response = unicode(user_collection_list([c1, c2], heading))

        # heading
        self.assertNotEqual(response.find(u'<h4>%s</h4' % heading), -1,
                            'collection list heading missing')
        # both items
        # TODO reverse URLs
        self.assert_(response.find(c1.get_url_path()) >= 0,
                            'collection UUID link missing')
        self.assert_(response.find(c2.get_url_path()) >= 0,
                            'collection nickname link missing')

        # empty collection, empty response
        response = unicode(user_collection_list([], heading))
        self.assertFalse(response, 'empty collection should not create a list')
