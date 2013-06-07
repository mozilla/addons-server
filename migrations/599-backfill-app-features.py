#!/usr/bin/env python
from django.db.utils import IntegrityError

from versions.models import Version
from mkt.webapps.models import AppFeatures, Webapp


def run():
    for app in Webapp.with_deleted.all():
        for ver in Version.with_deleted.filter(addon=app):
            try:
                ver.features
            except AppFeatures.DoesNotExist:
                try:
                    AppFeatures.objects.create(version=ver)
                except IntegrityError as e:
                    print ('[Webapp:%s] IntegrityError while trying to create '
                           'AppFeatures for version %s: %s' % (app.id, ver.id,
                                                               e))
                except Exception as e:
                    print ('[Webapp:%s] Exception while trying to create '
                           'AppFeatures for version %s: %s' % (app.id, ver.id,
                                                               e))
