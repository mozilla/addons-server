import json

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = ('Merge a series of fixtures and remove duplicates.')
    args = '[file ...]'

    def handle(self, *files, **options):
        """
        Load a bunch of json files.  Store the pk/model in a seen dictionary.
        Add all the unseen objects into output.
        """
        output = []
        seen = {}

        for f in files:
            f = file(f)
            data = json.loads(f.read())
            for object in data:
                key = '%s|%s' % (object['model'], object['pk'])
                if key not in seen:
                    seen[key] = 1
                    output.append(object)

        print json.dumps(output, indent=4)
