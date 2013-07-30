from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

import amo
from mkt.developers.forms import RegionForm
from mkt.regions import ALL_REGION_IDS, REGIONS_CHOICES_ID_DICT
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp

ALL_REGIONS = set(ALL_REGION_IDS)
DIVIDER = '-' * 28


class Command(BaseCommand):
    args = '<app_slug>'
    option_list = BaseCommand.option_list + (
        make_option('--exclude_region_by_id', action='store',
                    type='int', dest='exclude_region_id',
                    help='Adds an exclusion record for a region by id'),
        make_option('--include_region_by_id', action='store',
                    type='int', dest='include_region_id',
                    help='Removes an exclusion record for a region by id'),
    )
    help = ('Check regions for a given paid app and flag if they have '
            'incorrect regions.')

    def _region_obj(self, id_):
        return REGIONS_CHOICES_ID_DICT.get(id_)

    def _region_name(self, id_):
        region_obj_ = self._region_obj(id_)
        return unicode(region_obj_.name)

    def write_output(self, value=''):
        self.stdout.write(value + '\n')

    def write_error(self, value=''):
        self.stderr.write(value + '\n')

    def get_regions(self, app):
        region_excludes = (AER.objects.filter(addon=app)
                              .values_list('region', flat=True))
        return ALL_REGIONS.difference(region_excludes)

    def get_bad_regions(self, app, regions):
        # Initialise RegionForm so we can get the disabled region data
        # based on our app.

        if app.premium_type == amo.ADDON_FREE_INAPP:
            price = 'free'
        else:
            price = app.premium.price

        region_form = RegionForm(data={'regions': regions},
                                 product=app, price=price)

        # We manually construct bad_regions so we can make sure we catch
        # worldwide regions (Worldwide is not a valid choice in the form).
        return regions.intersection(region_form.disabled_regions)

    def exclude_region(self, app, app_slug, exclude_region_id):
        aer, created = AER.objects.get_or_create(addon=app,
                                                 region=exclude_region_id)
        if not created:
            self.write_error('Could not create exclusion record for '
                             'region_id %s (%s). It already exists' % (
                             exclude_region_id,
                             self._region_name(exclude_region_id)))
        else:
            self.write_output('')
            self.write_output("Excluding from region_id %s (%s) for "
                              "app '%s'" % (exclude_region_id,
                              self._region_name(exclude_region_id),
                              app_slug))
            self.include_exclude_region = True

    def include_region(self, app, app_slug, include_region_id):
        self.write_output()
        self.write_output("Including from region_id %s (%s) for app "
                          "'%s'" % (include_region_id,
                          self._region_name(include_region_id),
                          app_slug))
        try:
            aer = AER.objects.get(addon=app, region=include_region_id)
            aer.delete()
            self.include_exclude_region = True
        except AER.DoesNotExist:
            self.write_error('Could not remove exclusion record for '
                             'region_id %s (%s)' % (include_region_id,
                             self._region_name(include_region_id)))

    def output_regions(self, app, app_slug):
        regions = self.get_regions(app)
        bad_regions = self.get_bad_regions(app, regions)

        self.write_output('App Slug: %s' % app_slug)
        self.write_output('App Status: %s' % unicode(
                          amo.STATUS_CHOICES.get(app.status)))
        self.write_output('App Id: %s' % app.pk)
        self.write_output(DIVIDER)
        self.write_output('id | region.name')
        self.write_output(DIVIDER)

        has_bad_region = False
        for region_id in regions:
            region_name = self._region_name(region_id)
            asterisk = ''
            if region_id in bad_regions:
                has_bad_region = True
                asterisk = ' *'

            self.write_output('%s | %s%s' % (str(region_id).ljust(2),
                              region_name, asterisk))

        if has_bad_region:
            self.write_output('* Inappropriate region')

    def handle(self, *args, **options):
        self.include_exclude_region = False

        if not args:
            raise CommandError('An app_slug is required.')

        if len(args) > 1:
            raise CommandError('Only a single app_slug is accepted.')

        app_slug = args[0]

        # Look up the app by slug.
        try:
            app = Webapp.objects.get(app_slug=app_slug,
                                     premium_type__in=amo.ADDON_HAS_PAYMENTS)
        except Webapp.DoesNotExist:
            raise CommandError('Paid app with slug %s not '
                               'found.' % app_slug)

        # Bail if the app doesn't have a price.
        if (app.premium_type != amo.ADDON_FREE_INAPP and
                not app.has_premium() and
                not getattr('app.premium', 'price', False)):
            raise CommandError("App %s doesn't have a price" % app_slug)

        # Outputs the region info.
        self.output_regions(app, app_slug)

        # Handle including a region by deleting an exlusion record for the app.
        include_region_id = options.get('include_region_id')
        if include_region_id:
            self.include_region(app, app_slug, include_region_id)

        # Handle an exclusions record by adding an exclusion record for
        # the app.
        exclude_region_id = options.get('exclude_region_id')
        if exclude_region_id:
            self.exclude_region(app, app_slug, exclude_region_id)

        # If we've include/excluded a region show the regions now.
        if self.include_exclude_region:
            self.write_output()
            self.write_output('Regions are now as follows:')
            self.output_regions(app, app_slug)
