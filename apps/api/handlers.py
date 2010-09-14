import jingo
from piston.handler import BaseHandler
from piston.utils import rc, throttle

from users.models import UserProfile


class UserHandler(BaseHandler):
    allowed_methods = ('GET',)
    model = UserProfile

    def read(self, request):
        try:
            user = UserProfile.objects.get(user=request.user)
            return user
        except UserProfile.DoesNotExist:
            return None
