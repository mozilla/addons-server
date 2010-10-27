from django.core.management.base import BaseCommand


class Command(BaseCommand):

    def handle(self, *args, **kw):
        from versions.models import License
        qs = License.objects.filter(builtin=0)
        qs.filter(name=0).update(name=None)
        for lic in qs.filter(name=None):
            lic.name = 'Custom License'
            lic.save()
