from django.core.management.base import BaseCommand
from django.db.models import loading
from django.core.serializers import serialize
from django.db import models


def get_fields(obj):
    try:
        return obj._meta.fields
    except AttributeError:
        return []


class Command(BaseCommand):
    help = ('Dump specific objects from the database into JSON that you can '
            'use in a fixture')
    args = "[object_class id ...]"

    def handle(self, object_class, *ids, **options):
        (app_label, model_name) = object_class.split('.')
        dump_me = loading.get_model(app_label, model_name)
        obj = dump_me.objects.filter(id__in=[int(i) for i in ids])
        serialize_me = list(obj)
        index = 0

        while index < len(serialize_me):
            for field in get_fields(serialize_me[index]):
                if isinstance(field, models.ForeignKey):
                    serialize_me.append(
                            serialize_me[index].__getattribute__(field.name))

            index = index + 1

        serialize_me.reverse()
        print serialize('json', [o for o in serialize_me if o is not None],
                        indent=4)
