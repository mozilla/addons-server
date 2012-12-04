#!/usr/bin/env python
import amo
from mkt.webapps.models import Webapp


def run():
    """Add uuid to apps that don't have one."""
    for app in (Webapp.uncached.filter(guid=None)
                               .exclude(status=amo.STATUS_DELETED)
                               .no_transforms()):
        app.save()
