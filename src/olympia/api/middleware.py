from django.middleware.gzip import GZipMiddleware


class GZipMiddlewareForAPIOnly(GZipMiddleware):
    """
    Wrapper around GZipMiddleware, which only enables gzip for API responses.
    It specifically avoids enabling it for non-API responses because that might
    leak security tokens through the BREACH attack.

    https://www.djangoproject.com/weblog/2013/aug/06/breach-and-django/
    http://breachattack.com/
    https://bugzilla.mozilla.org/show_bug.cgi?id=960752
    """

    def process_response(self, request, response):
        if not request.path.startswith('/api/'):
            return response

        return super(GZipMiddlewareForAPIOnly, self).process_response(
            request, response
        )
