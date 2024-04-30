from django.db import migrations
from django.db.models import Value
from django.db.models.functions import Replace

def contributions_url_remove_www(apps, schema_editor):
    Addon = apps.get_model('addons', 'Addon')
    Addon.unfiltered.filter(contributions__startswith='https://www.buymeacoffee.com').update(
        contributions=Replace(
            'contributions',
            Value('www.buymeacoffee.com'),
            Value('buymeacoffee.com'),
        ),
    )

class Migration(migrations.Migration):
    dependencies = [
        ('addons', '0049_clear_bad_url_data'),
    ]
    operations = [migrations.RunPython(contributions_url_remove_www)]
