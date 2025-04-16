from olympia.hero.models import PrimaryHero
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

@task()
@use_primary_db
def sync_primary_hero_addon():
    invalid_heroes = []
    for hero in PrimaryHero.objects.filter(addon__isnull=True):
        promoted_addon = hero.promoted_addon

        if promoted_addon is None:
            invalid_heroes.append(hero)
        else:
            hero.addon = promoted_addon.addon
            hero.save()

    if len(invalid_heroes) > 0:
        raise ValueError(f'{invalid_heroes} heroes have no addon or legacy promoted addon')

