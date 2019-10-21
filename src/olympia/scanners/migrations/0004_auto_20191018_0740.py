from django.db import migrations

from olympia.constants.scanners import YARA


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0003_auto_20191017_1514'),
        ('yara', '0003_auto_20191010_1446'),
    ]

    operations = [
        migrations.RunSQL(
            [
                (
                    'INSERT INTO scanners_results ('
                    '  created,'
                    '  modified,'
                    '  upload_id,'
                    '  results,'
                    '  scanner,'
                    '  version_id,'
                    '  has_matches,'
                    '  matches'
                    ') '
                    'SELECT '
                    '  created,'
                    '  modified,'
                    '  upload_id,'
                    '  %s,'
                    '  %s,'
                    '  version_id,'
                    '  has_matches,'
                    '  matches '
                    'FROM yara_results;',
                    ['[]', YARA],  # [`results`, `scanner`]
                )
            ]
        )
    ]
