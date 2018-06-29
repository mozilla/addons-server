# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from olympia import amo
from olympia.addons.models import Addon, Persona
from olympia.bandwagon.models import Collection, FeaturedCollection
from olympia.constants.categories import CATEGORIES
from olympia.devhub.tasks import (
    pngcrush_existing_preview, pngcrush_existing_icons,
    pngcrush_existing_theme)
from olympia.discovery.data import discopane_items
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = 'Optimize existing images for "top" add-ons.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Do not really fire the tasks.')

    def handle(self, *args, **options):
        """Command entry point."""
        self.dry_run = options.get('dry_run', False)
        addons = self.fetch_addons()
        if not self.dry_run:
            self.crush_addons(addons)

    def crush_addons(self, addons):
        for addon in addons:
            if addon.is_persona():
                try:
                    if addon.persona.is_new():
                        pngcrush_existing_theme.delay(
                            addon.persona.pk,
                            set_modified_on=addon.serializable_reference())
                except Persona.DoesNotExist:
                    pass
            else:
                pngcrush_existing_icons.delay(
                    addon.pk, set_modified_on=addon.serializable_reference())
                for preview in addon.previews.all():
                    pngcrush_existing_preview.delay(
                        preview.pk,
                        set_modified_on=preview.serializable_reference())

    def fetch_addons(self):
        """
        Fetch the add-ons we want to optimize the images of. That'll be any
        add-on directly present on one of the landing pages (category landing
        pages, mozilla collections landing pages, homepage).
        """
        print('Starting to fetch all addons...')
        addons = set()

        print('Fetching featured add-ons.')
        for featuredcollection in FeaturedCollection.objects.all():
            addons.update(featuredcollection.collection.addons.all())

        print('Fetching mozilla collections add-ons.')
        try:
            mozilla = UserProfile.objects.get(username='mozilla')
            for collection in Collection.objects.filter(author=mozilla):
                addons.update(collection.addons.all())
        except UserProfile.DoesNotExist:
            print('Skipping mozilla collections as user does not exist.')

        print('Fetching 5 top-rated extensions/themes from each category.')
        for cat in CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION].values():
            addons.update(Addon.objects.public().filter(
                category=cat.id).order_by('-bayesian_rating')[:5])
        for cat in CATEGORIES[amo.FIREFOX.id][amo.ADDON_PERSONA].values():
            addons.update(Addon.objects.public().filter(
                category=cat.id).order_by('-bayesian_rating')[:5])

        print('Fetching 5 trending extensions/themes from each category.')
        for cat in CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION].values():
            addons.update(Addon.objects.public().filter(
                category=cat.id).order_by('-hotness')[:5])
        for cat in CATEGORIES[amo.FIREFOX.id][amo.ADDON_PERSONA].values():
            addons.update(Addon.objects.public().filter(
                category=cat.id).order_by('-hotness')[:5])

        print('Fetching 25 most popular themes.')
        addons.update(
            Addon.objects.public().filter(
                type=amo.ADDON_PERSONA).order_by('-average_daily_users')[:25])

        print('Fetching disco pane add-ons.')
        addons.update(
            Addon.objects.public().filter(
                id__in=[item.addon_id for item in discopane_items['default']]))

        print('Done fetching, %d add-ons to process total.' % len(addons))
        return addons
