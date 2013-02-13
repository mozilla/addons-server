import logging
import json

from django.db import transaction

from mkt.api.authentication import (MarketplaceAuthentication,
                                    PermissionAuthorization)
from mkt.api.base import MarketplaceResource

from .models import MonolithRecord

logger = logging.getLogger('z.monolith')


class MonolithData(MarketplaceResource):

    class Meta:
        queryset = MonolithRecord.objects.all()
        allowed_methods = ['get', 'delete']
        resource_name = 'data'
        filtering = {'recorded': ['exact', 'lt', 'lte', 'gt', 'gte'],
                     'key': ['exact'],
                     'id': ['lte', 'gte']}
        authorization = PermissionAuthorization('Monolith', 'API')
        authentication = MarketplaceAuthentication()

    @transaction.commit_on_success
    def obj_delete_list(self, request=None, **kwargs):
        filters = self.build_filters(request.GET)
        qs = self.get_object_list(request).filter(**filters)
        logger.info('deleting %d monolith resources' % qs.count())
        qs.delete()

    def dehydrate_value(self, bundle):
        return json.loads(bundle.data['value'])
