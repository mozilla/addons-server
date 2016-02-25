import json

from product_details.storage import PDFileStorage


class NoCachePDFileStorage(PDFileStorage):

    def data(self, name):
        """Return the parsed JSON data of the requested file name.

        Doesn't use the django-cache.
        """
        content = self.content(name)
        data = None

        if content:
            try:
                data = json.loads(content)
            except ValueError:
                return None

        return data
