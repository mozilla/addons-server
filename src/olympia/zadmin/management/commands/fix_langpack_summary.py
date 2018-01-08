from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q

from olympia.translations.models import Translation
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = "Fix summary of broken language packs for #5432"

    def handle(self, *args, **options):
        log = self.stdout.write

        owner = UserProfile.objects.get(email=settings.LANGPACK_OWNER_EMAIL)
        broken_langpacks = owner.addons.filter(Q(summary_id=F('name_id')))

        for langpack in broken_langpacks:
            log(u'Attempt to fix %s' % langpack)

            name_values_qset = (
                Translation.objects
                .filter(id=langpack.name.id)
                .values_list('locale', 'localized_string'))

            name_values = {locale: value for locale, value in name_values_qset}

            # Force `summary` to be set to a new translation instance
            delattr(langpack, 'summary_id')

            # Now set summary to all the values of `name` but with a new
            # translation object.
            langpack.summary = name_values

            langpack.save()

            assert langpack.summary_id != langpack.name_id

            log(u'fixed %s' % langpack)
