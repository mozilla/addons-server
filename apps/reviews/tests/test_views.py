import test_utils

from amo.urlresolvers import reverse


class TestViews(test_utils.TestCase):
    fixtures = ['reviews/dev-reply.json']

    def test_dev_reply(self):
        url = reverse('reviews.detail', args=[1865, 218468])
        r = self.client.get(url)
