import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand): #pragma: no cover
    help = ("Runs the indexer script for sphinx as defined in "
    " settings.SPHINX_INDEXER")

    requires_model_validation = False

    def handle(self, **options):
        try:
            os.execvp(settings.SPHINX_INDEXER,
                (settings.SPHINX_INDEXER, '--all', '--rotate', '--config',
                settings.SPHINX_CONFIG_FILE))

        except OSError:
            raise CommandError('You appear not to have the %r program '
            'installed or on your path' % settings.SPHINX_INDEXER)
