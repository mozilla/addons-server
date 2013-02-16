import amo
from addons.models import AddonCategory, Category, Webapp


def run():
    """
    Usage::

        python -B manage.py runscript scripts.generate-mkt-cats

    """

    cats = {
        'books-reference': 'Books & Reference',
        'education': 'Education',
        'entertainment-sports': 'Entertainment & Sports',
        'games': 'Games',
        'health-fitness': 'Health & Fitness',
        'lifestyle': 'Lifestyle',
        'music': 'Music',
        'news-weather': 'News & Weather',
        'photos-media': 'Photos & Media',
        'productivity': 'Productivity',
        'shopping': 'Shopping'
    }
    for slug, name in cats.iteritems():
        cat, created = Category.objects.get_or_create(type=amo.ADDON_WEBAPP,
                                                      slug=slug)
        if created:
            cat.name = name
            cat.save()
            print 'Created "%s" category' % name
        try:
            w = Webapp.objects.visible()[0]
        except IndexError:
            pass
        else:
            AddonCategory.objects.get_or_create(category=cat, addon=w)
            print 'Added "%s" to "%s" category' % (w.name, name)
