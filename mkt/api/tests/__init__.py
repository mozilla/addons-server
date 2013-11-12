import json
from amo.tests import TestCase


class BaseAPI(TestCase):
    """
    A base test case useful for API testing.
    """

    def _allowed_verbs(self, url, allowed):
        """
        Will run through all the verbs except the ones specified in allowed
        and ensure that hitting those produces a 405. Otherwise the test will
        fail.
        """
        verbs = ['get', 'post', 'put', 'patch', 'delete']
        for verb in verbs:
            if verb in allowed:
                continue
            try:
                res = getattr(self.client, verb)(url)
            except AttributeError:
                # Not all clients have patch.
                if verb != 'patch':
                    raise
            msg = 'Expected 40{1,3,5} for %s, got %s' % (verb.upper(),
                                                         res.status_code)
            assert res.status_code in (401, 403, 405), msg

    def get_error(self, response):
        return json.loads(response.content)['error_message']

