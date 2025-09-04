from olympia.amo.management import ProcessObjectsCommand
from olympia.files.models import File
from olympia.files.tasks import backfill_file_manifest


class Command(ProcessObjectsCommand):
    def get_model(self):
        return File

    def get_tasks(self):
        return {}
