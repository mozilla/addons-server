from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views


hero = SimpleRouter()
hero.register('primary', views.PrimaryHeroShelfViewSet,
              basename='hero-primary')

urlpatterns = [
    url(r'', include(hero.urls)),
    url(r'', views.HeroShelvesView.as_view(), name='hero-shelves')
]
