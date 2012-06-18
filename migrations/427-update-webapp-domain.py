from mkt.webapps.models import Webapp


def run():
    for app in Webapp.objects.all():
        app.update(app_domain=Webapp.domain_from_url(app.manifest_url))
