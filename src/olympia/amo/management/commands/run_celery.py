import os

from django.core.management.base import BaseCommand
from django.utils import autoreload

from olympia.amo.celery import app


root = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..')
pid_file = os.path.abspath(
    os.path.join(root, 'docker', 'artifacts', 'celery-worker.pid')
)

worker = app.Worker(loglevel='INFO', concurrency=2, logfile=pid_file, task_events=True)


def restart_celery():
    worker.start()


class Command(BaseCommand):
    def handle(self, *args, **options):
        print('Starting celery worker with autoreload...')

        autoreload.run_with_reloader(restart_celery)
