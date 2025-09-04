from olympia.amo.management import ProcessObjectsCommand
from olympia.files.models import File


class Command(ProcessObjectsCommand):
    def get_model(self):
        return File

    def get_tasks(self):
        return {}
