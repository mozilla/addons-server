from django.urls import include, re_path

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from .views import (
    ScannerQueryResultViewSet,
    ScannerQueryRuleViewSet,
    patch_scanner_result,
    push_scanner_result,
)


router = SimpleRouter()
router.register(r'query-rules', ScannerQueryRuleViewSet, basename='scanner-query-rule')

# Results are nested under their parent rule:
# /scanner/query-rules/{query_rule_pk}/results/
sub_rules = NestedSimpleRouter(router, r'query-rules', lookup='query_rule')
sub_rules.register(
    r'results', ScannerQueryResultViewSet, basename='scanner-query-rule-result'
)

urlpatterns = [
    re_path(r'^results/$', push_scanner_result, name='scanner-result-push'),
    re_path(
        r'^results/(?P<pk>\d+)/$',
        patch_scanner_result,
        name='scanner-result-patch',
    ),
    re_path(r'', include(router.urls)),
    re_path(r'', include(sub_rules.urls)),
]
