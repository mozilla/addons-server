from django import test

from nose.tools import eq_

import amo
from bandwagon.helpers import user_collection_list
from bandwagon.models import Collection


class TestHelpers(test.TestCase):

    def test_user_collection_list(self):
        c1 = Collection(uuid='eb4e3cd8-5cf1-4832-86fb-a90fc6d3765c')
        c2 = Collection(uuid='61780943-e159-4206-8acd-0ae9f63f294c',
                        nickname='my_collection')
        heading = 'My Heading'
        response = unicode(user_collection_list([c1, c2], heading))

        # heading
        self.assertNotEqual(response.find(u'<h4>%s</h4' % heading), -1,
                            'collection list heading missing')
        # both items
        # TODO reverse URLs
        self.assert_(response.find(u'/collection/%s' % c1.uuid) >= 0,
                            'collection UUID link missing')
        self.assert_(response.find(u'/collection/%s' % c2.nickname) >= 0,
                            'collection nickname link missing')
        self.assert_(response.find(u'/collection/%s' % c2.uuid) == -1,
                         'collection with nickname should not have UUID link')

        # empty collection, empty response
        response = unicode(user_collection_list([], heading))
        self.assertFalse(response, 'empty collection should not create a list')
