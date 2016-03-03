import json

from product_details.storage import PDFileStorage


class NoCachePDFileStorage(PDFileStorage):
    json_data = {}

    def data(self, name):
        """Return the parsed JSON data of the requested file name.

        Doesn't use the django-cache.
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
