from django.conf import settings

from seclusion.base import Client

client = None


def get_client():
    # If you haven't specified a seclusion host, we can't do anything.
    if settings.SECLUSION_HOSTS:
        config = {
            # TODO: when seclusion can cope with multiple hosts, we'll pass
            # them all through and let seclusion do its magic.
            'server': settings.SECLUSION_HOSTS[0],
            'key': settings.SECLUSION_KEY,
            'secret': settings.SECLUSION_SECRET
        }
        return Client(config)

if not client:
    client = get_client()
