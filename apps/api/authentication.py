import jingo
from piston import authentication

from access.middleware import ACLMiddleware
from zadmin import jinja_for_django


jfd = lambda a, b, c: jinja_for_django(a, b, context_instance=c)
authentication.render_to_response = jfd


class AMOOAuthAuthentication(authentication.OAuthAuthentication):
    """^^^MOO!!!  Adds amo_user to the request object."""

    def is_authenticated(self, request):
        if request.user.is_authenticated():
            return True

        rv = super(AMOOAuthAuthentication, self).is_authenticated(request)

        if rv:
            ACLMiddleware().process_request(request)

        return rv

    def challenge(self, request):
        response = jingo.render(request, 'oauth/challenge.html', status=401)
        response['WWW-Authenticate'] = 'OAuth realm="API"'
        return response
