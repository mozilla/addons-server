from pyquery import PyQuery as pq

from olympia.amo.tests import BaseTestCase
from olympia.bandwagon.models import Collection
from olympia.bandwagon.templatetags.jinja_helpers import user_collection_list


class TestHelpers(BaseTestCase):
    def test_user_collection_list(self):
        c1 = Collection(uuid='eb4e3cd8-5cf1-4832-86fb-a90fc6d3765c')
        c2 = Collection(uuid='61780943-e159-4206-8acd-0ae9f63f294c',
                        nickname='my_collection')
        heading = 'My Heading'
        response = unicode(user_collection_list([c1, c2], heading))

        # heading
        assert pq(response)('h3').text() == heading

        # both items
        # TODO reverse URLs
        assert c1.get_url_path() in response, 'Collection UUID link missing.'
        assert c2.get_url_path() in response, (
            'Collection nickname link missing.')

        # empty collection, empty response
        response = unicode(user_collection_list([], heading))
        assert not response, 'empty collection should not create a list'
