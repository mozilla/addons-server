#!/usr/bin/env python

from addons.models import Addon

from olympia import amo


def run():
    """
    Migrate summary to description field for a handful of themes after
    getpersonas migration.
    """
    addons = Addon.objects.filter(
        type=amo.ADDON_PERSONA, description__isnull=True, summary__isnull=False
    )
    for addon in addons:
        addon.description = addon.summary
        addon.save()
