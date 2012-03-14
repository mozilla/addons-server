from django.conf.urls.defaults import include, patterns

from reviews.urls import review_patterns


APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""

urlpatterns = patterns('',
    # TODO: Port reviews and add to `mkt/details`.
    ('^app/%s/reviews/' % APP_SLUG, include(review_patterns('apps'))),
)
