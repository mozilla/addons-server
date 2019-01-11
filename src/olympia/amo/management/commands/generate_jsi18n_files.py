# -*- coding: utf-8 -*-
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.http import HttpRequest
from django.utils import translation
from django.views.i18n import javascript_catalog


class Command(BaseCommand):
    help = 'Generate static jsi18n files for each locale we support'

    def handle(self, *args, **options):
        fake_request = HttpRequest()
        for lang in settings.AMO_LANGUAGES:
            filename = os.path.realpath(os.path.join(
                settings.STATICFILES_DIRS[0], 'js', 'i18n', '%s.js' % lang))
            with translation.override(lang):
                response = javascript_catalog(fake_request)
                with open(filename, 'w') as f:
                    f.write(response.content)
