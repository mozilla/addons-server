import os

from django.db.models import Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.translations.models import Translation


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Translation

    def get_tasks(self):
        return {
            'copy_spanish_translations': {
#                'task': ...,
                'queryset_filters': [Q(locale='es')],
            },
        }
