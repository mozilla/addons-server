from django.db.models import Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.versions.models import Version
from olympia.versions.tasks import hard_delete_versions


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Version

    def get_tasks(self):
        return {
            'delete_versions_without_files': {
                'task': hard_delete_versions,
                'queryset_filters': [Q(files__id=None)],
            },
        }
