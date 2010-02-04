from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^featured$', views.featured, name='nick.featured'),
    url('^category_featured$', views.category_featured,
        name='nick.category_featured'),
    url('^featured\+categories$', views.combo, name='nick.combo'),
    url('^popular$', views.popular, name='nick.popular'),
)
