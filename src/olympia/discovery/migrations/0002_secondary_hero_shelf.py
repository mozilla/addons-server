from django.db import migrations


class Migration(migrations.Migration):
    """Needed to move this to a separate migration to avoid a circular
    dependency.  PrimaryHero requires discovery migrations to be complete (due
    to a foreign key to DiscoveryItem); the SecondaryHeroShelf model in
    discovery/admin is a proxy call to SecondaryHero in hero/models."""

    initial = True

    dependencies = [
        ('discovery', '0001_initial'),
        ('hero', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SecondaryHeroShelf',
            fields=[
            ],
            options={
                'verbose_name_plural': 'secondary hero shelves',
                'get_latest_by': 'created',
                'abstract': False,
                'proxy': True,
                'base_manager_name': 'objects',
                'indexes': [],
                'constraints': [],
            },
            bases=('hero.secondaryhero',),
        ),
    ]
