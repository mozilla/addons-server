from .httphost import set_host_info


class HTTPHostMiddleware:
    """
    Stores globally accessible metadata about the host.

    This requires the server (Apache or whatever) to set HTTP_HOST.
    """

    def process_request(self, request):
        # e.g. telefonica.marketplace.mozilla.org
        set_host_info(request.META.get('HTTP_HOST', ''))
