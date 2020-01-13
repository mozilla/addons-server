from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views


hero = SimpleRouter()
hero.register('primary', views.PrimaryHeroShelfViewSet,
              basename='hero-primary')
hero.register('secondary', views.SecondaryHeroShelfViewSet,
              basename='hero-secondary')

urlpatterns = [
    url(r'', include(hero.urls)),
    url(r'', views.HeroShelvesView.as_view(), name='hero-shelves')
]
