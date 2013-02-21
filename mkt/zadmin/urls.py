from django.conf.urls import patterns, url

from . import views

urlpatterns = patterns(
    '',
    # Featured apps selector.
    url('^apps/featured$', views.featured_apps_admin,
        name='zadmin.featured_apps'),
    url('^apps/featured_ajax$', views.featured_apps_ajax,
        name='zadmin.featured_apps_ajax'),
    url('^apps/featured_categories_ajax$', views.featured_categories_ajax,
        name='zadmin.featured_categories_ajax'),
    url('^apps/set_attrs_ajax$', views.set_attrs_ajax,
        name='zadmin.set_attrs_ajax'),
    url('^manifest-revalidation$', views.manifest_revalidation,
        name='zadmin.manifest_revalidation'),
)
