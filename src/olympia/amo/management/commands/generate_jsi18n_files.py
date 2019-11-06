# -*- coding: utf-8 -*-
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.http import HttpRequest
from django.utils import translation
from django.utils.encoding import force_text
from django.views.i18n import JavaScriptCatalog


class Command(BaseCommand):
    help = 'Generate static jsi18n files for each locale we support'
    requires_system_checks = False  # Can be ran without the database up yet.

    def handle(self, *args, **options):
        fake_request = HttpRequest()
        fake_request.method = 'GET'
        for lang in settings.AMO_LANGUAGES:
            filename = os.path.join(
                settings.STATICFILES_DIRS[0], 'js', 'i18n', '%s.js' % lang
            )
            with translation.override(lang):
                response = JavaScriptCatalog.as_view()(fake_request)
                with open(filename, 'w') as f:
                    f.write(force_text(response.content))
