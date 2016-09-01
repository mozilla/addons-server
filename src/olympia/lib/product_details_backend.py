import json

from product_details.storage import PDFileStorage


class NoCachePDFileStorage(PDFileStorage):
    json_data = {}

    def data(self, name):
        """Return the parsed JSON data of the requested file name.

        Doesn't use the django-cache, doesn't validate the name, just gets the
        data from the filesystem using self.content() and store it in a dict
        on the product details backend instance.

        It makes it more efficient than just using PDFileStorage with a dummy
        cache backend, because we do store the result, just not in a cache
        backend that needs network round-trips, and we avoid walking the
        filesystem entirely.
        """
        cache_key = self._get_cache_key(name)

        data = self.json_data.get(cache_key)

        if data is None:
            content = self.content(name)

            if content:
                try:
                    data = json.loads(content)
                except ValueError:
                    return None

            self.json_data[cache_key] = data

        return data
