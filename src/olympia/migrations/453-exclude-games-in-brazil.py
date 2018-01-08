import mkt

from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


def run():
    """Exclude Games in Brazil."""
    games = Webapp.category('games')
    if games:
        apps = Webapp.objects.filter(categories=games.id)
        for app in apps:
            AER.objects.get_or_create(addon=app, region=mkt.regions.BR.id)
