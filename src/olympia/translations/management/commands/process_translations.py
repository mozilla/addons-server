import os

from django.db.models import Q

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.management import ProcessObjectsCommand
from olympia.translations.models import Translation
from olympia.translations.tasks import strip_html_from_summaries, update_outgoing_url


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
            'strip_html_from_summaries': {
                'task': strip_html_from_summaries,
                'queryset_filters': [
                    Q(
                        id__in=Addon.unfiltered.filter(
                            status=amo.STATUS_APPROVED, summary__isnull=False
                        ).values_list('summary', flat=True)
                    ),
                    # Crude, but enough for our needs (cleaning up old
                    # summaries).
                    Q(localized_string_clean__contains='href='),
                ],
            },
        }
