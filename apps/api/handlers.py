import jingo
from piston.handler import BaseHandler
from piston.utils import rc, throttle
from piston.authentication import OAuthAuthentication


from users.models import UserProfile


# Monkeypatch to render Piston's oauth page.
def challenge(self, request):
    response = jingo.render(request, 'oauth/challenge.html', status=401)
    response['WWW-Authenticate'] = 'OAuth realm="API"'
    return response


OAuthAuthentication.challenge = challenge


class UserHandler(BaseHandler):
    allowed_methods = ('GET',)
    fields = ('email',)
    model = UserProfile

    def read(self, request):
        try:
            user = UserProfile.objects.get(user=request.user)
            return user
        except UserProfile.DoesNotExist:
            return None
