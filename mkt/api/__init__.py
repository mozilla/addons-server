from django.conf import settings
from django.db.models.signals import post_save, post_delete

from piston.models import consumer_post_save, consumer_post_delete, Consumer
from piston import utils

from amo.decorators import json_response

# These send emails to the user about the creation of the OAuth tokens
# within the site. We don't want that.
post_save.disconnect(consumer_post_save, sender=Consumer)
post_delete.disconnect(consumer_post_delete, sender=Consumer)


# Monkey patch the rc handler in django-piston so that all the rc responses
# that piston will return are JSON. It's nicer to write an API if we are
# consistent.
class json_factory(utils.rc_factory):

    def __getattr__(self, attr):
        response = super(json_factory, self).__getattr__(attr)
        if response.status_code >= 300:
            return json_response({'error': response.content},
                                 status_code=response.status_code)
        return response

if settings.MARKETPLACE:
    utils.rc = json_factory()
