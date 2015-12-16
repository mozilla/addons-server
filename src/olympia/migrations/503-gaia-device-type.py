#!/usr/bin/env python

from celeryutils import task

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count

from olympia import amo
from addons.models import AddonDeviceType as ADT
from amo.decorators import write
from amo.utils import chunked


@task
@write
def _task(**kw):
    # Remove any dupes. `UNIQUE` constraint introduced in migration 504.
    dupes = (ADT.objects.values_list('addon', 'device_type')
                        .annotate(c=Count('id')).filter(c__gt=1))
    for addon, device_type, total in dupes:
        devices = ADT.objects.filter(addon_id=addon, device_type=device_type)
        for d in devices[:total - 1]:
            d.delete()

    # Remove stale device types.
    devices = ADT.objects.all()
    for chunk in chunked(devices, 50):
        for device in chunk:
            try:
                device.addon
            except ObjectDoesNotExist:
                device.delete()

    # `DEVICE_MOBILE` -> `DEVICE_MOBILE` and `DEVICE_GAIA`.
    devices = ADT.objects.filter(device_type=amo.DEVICE_MOBILE.id)

    for chunk in chunked(devices, 50):
        for device in chunk:
            if amo.DEVICE_GAIA in device.addon.device_types:
                continue
            device.id = None
            device.device_type = amo.DEVICE_GAIA.id
            device.save()
            device.addon.save()


def run():
    """Mark mobile-compatible apps as compatible for Firefox OS as well."""
    _task()
