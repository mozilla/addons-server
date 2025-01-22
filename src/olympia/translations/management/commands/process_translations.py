import os

from django.db.models import Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.translations.models import Translation
from olympia.translations.tasks import update_outgoing_url


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Translation

    def get_tasks(self):
        # Change this on dev/stage using an environement variable. The trailing
        # slash is important (matches how settings.REDIRECT_URL is set).
        old_outgoing_url = os.environ.get(
            'OLD_OUTGOING_URL', 'https://outgoing.prod.mozaws.net/v1/'
        )
        return {
            'update_outgoing_url': {
                'task': update_outgoing_url,
                'queryset_filters': [
                    Q(localized_string_clean__icontains=old_outgoing_url),
                ],
                'kwargs': {'old_outgoing_url': old_outgoing_url},
            },
        }
