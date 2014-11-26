#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os.path
import sys

sys.path.append(os.path.realpath(
    os.path.join(os.path.dirname(__file__), '../')))
import manage  # noqa (we need this in standalone scripts)

import amo
from addons.models import Addon
from lib.crypto import packaged


def get_addons():
    return Addon.objects.all()


def get_versions(addon):
    return addon.versions.all()


def sign_version(version):
    # Addon can be signed if it's either public or preliminary reviewed.
    is_signable = (
        not version.deleted and version.addon.is_public() and
        all(f.status in (amo.STATUS_PUBLIC, amo.STATUS_LITE)
            for f in version.all_files))

    if not is_signable:
        return

    # Calling signature service task.
    packaged.sign.delay(version.pk, reviewer=False)


def main():
    for addon in get_addons():
        for version in get_versions(addon):
            sign_version(version)

if __name__ == '__main__':
    main()
