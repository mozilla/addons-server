from bandwagon.models import Collection


def run():
    # Rename collection for homepage-featured apps.
    home = Collection.objects.get(
        author__username='mozilla', slug='webapps_home'
    )
    home.slug = 'featured_apps_home'
    home.save()

    # Rename collection for category-featured apps.
    cat = Collection.objects.get(
        author__username='mozilla', slug='webapps_featured'
    )
    cat.slug = 'featured_apps_category'
    cat.save()
