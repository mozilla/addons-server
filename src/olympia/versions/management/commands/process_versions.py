from django.db.models import Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.versions.models import Version
from olympia.versions.tasks import soft_block_versions


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Version

    def get_tasks(self):
        return {
            'block_old_deleted_versions': {
                'task': soft_block_versions,
                'queryset_filters': [Q(deleted=True, blockversion__id=None)],
            },
        }
