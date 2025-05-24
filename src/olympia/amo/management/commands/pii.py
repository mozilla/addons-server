from typing import Type

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

from olympia.amo.models import ModelBase
import olympia.core.logger


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.amo')
    requires_system_checks = []

    def sorted_models(self) -> list[Type[ModelBase]]:
        all_models = apps.get_models()
        return sorted(
            [model for model in all_models if model.__module__.startswith('olympia.')],
            key=lambda model: model.__name__,
        )

    def handle(self, *args, **options):
        models = self.sorted_models()

        self.log.info(
            f'Checking models: {", ".join([model.__name__ for model in models])}'
        )
        for model in models:
            pii_fields = model._pii_fields
            if len(pii_fields) > 0:
                self.log.info(f'{model.__name__}: {", ".join(pii_fields)}')
