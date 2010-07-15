from nose.tools import eq_, with_setup
import test_utils

from bandwagon.models import Collection


class TestViews(test_utils.TestCase):
    fixtures = ['bandwagon/test_models.json']

    def check_response(self, url, code, to=None):
        response = self.client.get(url, follow=True)
        if code == 404:
            eq_(response.status_code, 404)
        elif code in (301, 302):
            self.assertRedirects(response, to, status_code=code)
        else:
            assert code in (301, 302, 404), code

    def test_legacy_redirects(self):
        collection = Collection.objects.get(nickname='wut')
        url = collection.get_url_path()
        tests = [
            ('/collection/wut', 301, url),
            ('/collection/wut/', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4/', 301, url),
            ('/collection/404', 404)]
        for test in tests:
            self.check_response(*test)
