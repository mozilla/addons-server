from typing import Type

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

import olympia.core.logger


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.amo')
    requires_system_checks = []

    def get_pii_fields(self, model_class: Type[models.Model]):
        pii_fields = []
        for field in model_class._meta.fields:
            if getattr(field, 'is_pii', False):
                pii_fields.append(field.name)
        return pii_fields

    def models(self):
        all_models = apps.get_models()
        return sorted(
            [model for model in all_models],
            key=lambda model: model.__name__,
        )

    def handle(self, *args, **options):
        models = self.models()

        self.log.info(
            f'Checking models: {", ".join([model.__name__ for model in models])}'
        )
        for model in models:
            pii_fields = self.get_pii_fields(model)
            if len(pii_fields) > 0:
                self.log.info(f'{model.__name__}: {", ".join(pii_fields)}')
