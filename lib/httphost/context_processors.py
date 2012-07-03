from lib import httphost


def httphost_context(request):
    """Exposes SITE_URL and SUBDOMAIN to the request context."""
    return {'SITE_URL': httphost.site_url(),
            'SUBDOMAIN': httphost.subdomain()}
