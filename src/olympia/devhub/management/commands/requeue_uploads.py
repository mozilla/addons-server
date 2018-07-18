from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Requeue any stranded add-on uploads after restarting Rabbit."

    def handle(self, *args, **options):
        from olympia.files.models import FileUpload
        from olympia.devhub import tasks

        qs = FileUpload.objects.filter(validation=None)
        pks = qs.values_list('pk', flat=True)
        print('Restarting %s tasks.' % len(pks))
        for pk in pks:
            tasks.validator.delay(pk)
