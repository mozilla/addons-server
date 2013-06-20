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
            assert res.status_code in (401, 405), (
                '%s: %s not 401 or 405' % (verb.upper(), res.status_code))

    def get_error(self, response):
        return json.loads(response.content)['error_message']

