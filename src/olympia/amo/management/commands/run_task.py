from django.core.management.base import BaseCommand

from olympia.amo.celery import app

class Command(BaseCommand):
    help = 'Queue a task to run'

    def add_arguments(self, parser):
        parser.add_argument('task_name', type=str, help='Name of the task to run')

    def handle(self, *args, **options):
        app.send_task(options['task_name'])
