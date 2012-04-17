import jingo
from django.shortcuts import redirect
from django.db import transaction
from tower import ugettext as _

import amo
from amo import messages
from amo.urlresolvers import reverse
from bandwagon.models import CollectionAddon, Collection
from users.models import UserProfile

from mkt.webapps.models import Webapp


@transaction.commit_on_success
def featured_apps_admin(request):
    author =  UserProfile.objects.get(username="mozilla")
    home_collection = Collection.objects.get(author=author,
                                             slug="webapps_home",
                                             type=amo.COLLECTION_FEATURED)
    featured_collection = Collection.objects.get(author=author,
                                                 slug="webapps_featured",
                                                 type=amo.COLLECTION_FEATURED)
    if request.POST:
        if 'home_submit' in request.POST:
            coll = home_collection
            rowid = 'home'
        elif 'featured_submit' in request.POST:
            coll = featured_collection
            rowid = 'featured'
        existing = set(coll.addons.values_list('id', flat=True))
        requested = set(int(request.POST[k]) for k in sorted(request.POST.keys())
                        if k.endswith(rowid + '-webapp'))
        CollectionAddon.objects.filter(collection=coll, addon__in=(existing - requested)).delete()
        for id in requested - existing:
            CollectionAddon.objects.create(collection=coll, addon=Webapp.objects.get(id=id))
        messages.success(request, _('Changes successfully saved.'))
        return redirect(reverse('admin.featured_apps'))

    def get(collection):
        return (c.addon for c in
                CollectionAddon.objects.filter(collection=collection))

    return jingo.render(request, 'zadmin/featuredapp.html',
                        {"home_addons": enumerate(get(home_collection)),
                         "featured_addons": enumerate(get(featured_collection))})
