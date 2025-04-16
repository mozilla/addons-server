import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.hero.models import PrimaryHero


log = olympia.core.logger.getLogger('z.hero')


@task
@use_primary_db
def sync_primary_hero_addon():
    invalid_heroes = []
    for hero in PrimaryHero.objects.filter(addon__isnull=True):
        promoted_addon = hero.promoted_addon

        if promoted_addon is None:
            invalid_heroes.append(hero)
        else:
            log.info(f'Syncing hero {hero} with promoted addon {hero.promoted_addon}')
            hero.addon = promoted_addon.addon
            hero.save()

    if len(invalid_heroes) > 0:
        log.error(f'Invalid PrimaryHero records: {invalid_heroes}')
