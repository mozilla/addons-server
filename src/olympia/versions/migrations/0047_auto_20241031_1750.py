# Generated by Django 4.2.16 on 2024-11-01 09:30

from django.db import migrations
from django.conf import settings

from olympia.constants.licenses import *

BUILTIN_MAP = [
    # (License object, previous builtin, new builtin)
    (LICENSE_GPL2, 2, 3),
    (LICENSE_GPL3, 3, 4),
    (LICENSE_LGPL2, 4, 5),
    (LICENSE_LGPL3, 5, 6),
    (LICENSE_MIT, 6, 8),
    (LICENSE_BSD, 7, 10),
    (LICENSE_MPL1, 10, 11),
    (LICENSE_CC_COPYRIGHT, 11, 12),
    (LICENSE_CC_BY30, 12, 13),
    (LICENSE_CC_BY_NC30, 13, 14),
    (LICENSE_CC_BY_NC_ND30, 14, 15),
    (LICENSE_CC_BY_NC_SA30, 15, 16),
    (LICENSE_CC_BY_ND30, 16, 17),
    (LICENSE_CC_BY40, 17, 18),
    (LICENSE_COPYRIGHT_AR, 18, 26),
]


def set_new_builtins(apps, schema_editor):
    License = apps.get_model('versions', 'License')

    for i in reversed(BUILTIN_MAP):
        try:
            # not all the licenses exist. If not, we skip it.
            license = License.objects.get(builtin=i[1])
        except:
            continue

        if license.builtin != i[0].builtin:
            license.update(builtin=i[2])

    if settings.TESTING_ENV == False:
        for license in ALL_LICENSES:
            try:
                License.objects.get_or_create(builtin=license.builtin)
            except Exception:
                continue

def restore_old_builtins(apps, schema_editor):
    License = apps.get_model('versions', 'License')

    for i in BUILTIN_MAP:
        try:
            # not all the licenses exist. If not, we skip it.
            license = License.objects.get(builtin=i[2])
        except:
            continue
        if license.builtin != i[0].builtin:
            license.update(builtin=i[1])


class Migration(migrations.Migration):

    dependencies = [
        ('versions', '0046_auto_20240916_1240'),
    ]

    operations = [
        migrations.RunPython(set_new_builtins, restore_old_builtins),
    ]
