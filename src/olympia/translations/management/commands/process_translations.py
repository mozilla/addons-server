from django.db.models import F, Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.bandwagon.models import Collection
from olympia.translations.models import Translation
from olympia.translations.tasks import reclean_collection_descriptions


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Translation

    def get_tasks(self):
        return {
            'reclean_collection_descriptions': {
                'task': reclean_collection_descriptions,
                # Need to fetch ids of translations that belong to collection
                # descriptions (there might be more than one per collection!)
                # and then find those where the cleaned string is not the same
                # as the original: those are the ones we need to re-clean.
                'queryset_filters': [
                    Q(
                        id__in=Collection.objects.all()
                        .filter(description__isnull=False)
                        .values_list('description', flat=True)
                    ),
                    Q(localized_string_clean__isnull=False),
                    ~Q(localized_string_clean=F('localized_string')),
                ],
            },
        }
