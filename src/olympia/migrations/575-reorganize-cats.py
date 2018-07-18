from addons.models import Category

from olympia import amo


def run():
    """
    We reorganized our categories:

        https://bugzilla.mozilla.org/show_bug.cgi?id=854499

    Usage::

        python -B manage.py runscript migrations.575-reorganize-cats

    """

    all_cats = Category.objects.filter(type=amo.ADDON_WEBAPP)

    # (1) "Entertainment & Sports" becomes "Entertainment" and "Sports."
    try:
        entertainment = all_cats.filter(slug='entertainment-sports')[0]
    except IndexError:
        print('Could not find Category with slug="entertainment-sports"')
    else:
        # (a) Change name of the category to "Entertainment."
        entertainment.name = 'Entertainment'
        entertainment.slug = 'entertainment'
        entertainment.save()
        print('Renamed "Entertainment & Sports" to "Entertainment"')

    # (b) Create a new category called "Sports."
    Category.objects.create(
        type=amo.ADDON_WEBAPP, slug='sports', name='Sports'
    )
    print('Created "Sports"')

    # --

    # (2) "Music & Audio" becomes "Music".
    try:
        music = all_cats.filter(slug='music')[0]
    except IndexError:
        print('Could not find Category with slug="music"')
    else:
        music.name = 'Music'
        music.save()
        print('Renamed "Music & Audio" to "Music"')

    # --

    # (3) "Social & Communication" becomes "Social".
    try:
        social = all_cats.filter(slug='social')[0]
    except IndexError:
        print('Could not find Category with slug="social"')
    else:
        social.name = 'Social'
        social.save()
        print('Renamed "Social & Communication" to "Social"')

    # --

    # (4) "Books & Reference" becomes "Books" and "Reference."
    try:
        books = all_cats.filter(slug='books-reference')[0]
    except IndexError:
        print('Could not find Category with slug="books-reference"')
    else:
        # (a) Change name of the category to "Books.""
        books.name = 'Books'
        books.slug = 'books'
        books.save()
        print('Renamed "Books & Reference" to "Books"')

    # (b) Create a new category called "Reference."
    Category.objects.create(
        type=amo.ADDON_WEBAPP, slug='reference', name='Reference'
    )
    print('Created "Reference"')

    # --

    # (5) "Photos & Media" becomes "Photo & Video."
    try:
        photos = all_cats.filter(slug='photos-media')[0]
    except IndexError:
        print('Could not find Category with slug="photos-media"')
    else:
        photos.name = 'Photo & Video'
        photos.slug = 'photo-video'
        photos.save()
        print('Renamed "Photos & Media" to "Photo & Video"')

    # --

    # (6) Add "Maps & Navigation."
    Category.objects.create(
        type=amo.ADDON_WEBAPP, slug='maps-navigation', name='Maps & Navigation'
    )
    print('Created "Maps & Navigation"')
