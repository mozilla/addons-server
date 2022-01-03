from django.utils.deprecation import MiddlewareMixin

import olympia.core.logger
from olympia import core


log = olympia.core.logger.getLogger('z.access')


class UserAndAddrMiddleware(MiddlewareMixin):
    """Persist user and remote addr in current thread while processing the
    request."""
    def process_request(self, request):
        # Persist the user and remote addr in the thread to make it accessible
        # in log() statements etc. `user` could be anonymous here, it's kept
        # lazy to avoid early database queries.
        core.set_user(request.user)
        core.set_remote_addr(request.META.get('REMOTE_ADDR'))

    def process_response(self, request, response):
        core.set_user(None)
        core.set_remote_addr(None)
        return response

    def process_exception(self, request, exception):
        core.set_user(None)
        core.set_remote_addr(None)
