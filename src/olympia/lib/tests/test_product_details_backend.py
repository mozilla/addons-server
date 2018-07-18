import json

from tempfile import mkdtemp

from django.conf import settings

from mock import patch

from olympia.lib.product_details_backend import NoCachePDFileStorage


class TestNoCachePDFileStorage(object):
    def setup(self):
        self.storage = NoCachePDFileStorage(
            json_dir=mkdtemp(dir=settings.TMP_PATH)
        )
        self.storage.clear_cache()

    def test_no_cache(self):
        good_data = {'dude': 'abiding'}
        with patch.object(
            self.storage, 'content', return_value=json.dumps(good_data)
        ) as content_mock:

            assert self.storage.data('test.json') == good_data
            content_mock.assert_called_once_with('test.json')

        # make sure nothing was put in the django-cache
        cache_key = self.storage._get_cache_key('test.json')
        data = self.storage._cache.get(cache_key)

        assert data is None

        # We're storing the data on the class itself
        assert self.storage.json_data[cache_key] == good_data
