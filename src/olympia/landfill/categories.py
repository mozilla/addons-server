from addons.models import Category
from constants.base import ADDON_EXTENSION, ADDON_PERSONA

from .translations import generate_translations


# Based on production categories.
addons_categories = {
    'firefox': (
        # (Label in production, Default icon name),
        (u'Alerts & Updates', u'alerts'),
        (u'Appearance', u'appearance'),
        (u'Bookmarks', u'bookmarks'),
        (u'Download Management', u'downloads'),
        (u'Feeds, News & Blogging', u'feeds'),
        (u'Games & Entertainment', u'games'),
        (u'Language Support', u'dictionary'),
        (u'Photos, Music & Videos', u'photos'),
        (u'Privacy & Security', u'security'),
        (u'Search Tools', u'search'),
        (u'Shopping', u'shopping'),
        (u'Social & Communication', u'social'),
        (u'Tabs', u'tabs'),
        (u'Web Development', u'webdev'),
        (u'Other', u'default'),
    ),
    'thunderbird': (
        # (Label in production, Default icon name),
        (u'Appearance and Customization', u'appearance'),
        (u'Calendar and Date/Time', u'video'),
        (u'Chat and IM', u'social'),
        (u'Contacts', u'music'),
        (u'Folders and Filters', u'shopping'),
        (u'Import/Export', u'downloads'),
        (u'Language Support', u'dictionary'),
        (u'Message Composition', u'posts'),
        (u'Message and News Reading', u'feeds'),
        (u'Miscellaneous', u'default'),
        (u'Privacy and Security', u'alerts'),
        (u'Tags', u'bookmarks'),
    ),
    'android': (
        # (Label in production, Default icon name),
        (u'Device Features & Location', u'search'),
        (u'Experimental', u'alerts'),
        (u'Feeds, News, & Blogging', u'feeds'),
        (u'Performance', u'webdev'),
        (u'Photos & Media', u'photos'),
        (u'Security & Privacy', u'security'),
        (u'Shopping', u'shopping'),
        (u'Social Networking', u'social'),
        (u'Sports & Games', u'games'),
        (u'User Interface', u'tabs'),
    ),
    'seamonkey': (
        # (Label in production, Default icon name),
        (u'Bookmarks', u'bookmarks'),
        (u'Downloading and File Management', u'downloads'),
        (u'Interface Customizations', u'appearance'),
        (u'Language Support & Translation', u'dictionary'),
        (u'Miscellaneous', u'default'),
        (u'Photos & Media', u'photos'),
        (u'Privacy and Security', u'alerts'),
        (u'RSS, News and Blogging', u'feeds'),
        (u'Search Tools', u'search'),
        (u'Site-specific', u'posts'),
        (u'User Interface', u'tabs'),
        (u'Web and Developer Tools', u'webdev'),
    ),
}


themes_categories = (
    # (Label in production, slug),
    (u'Abstract', u'abstract'),
    (u'Causes', u'causes'),
    (u'Fashion', u'fashion'),
    (u'Film and TV', u'film-and-tv'),
    (u'Firefox', u'firefox'),
    (u'Foxkeh', u'foxkeh'),
    (u'Holiday', u'holiday'),
    (u'Music', u'music'),
    (u'Nature', u'nature'),
    (u'Other', u'other'),
    (u'Scenery', u'scenery'),
    (u'Seasonal', u'seasonal'),
    (u'Solid', u'solid'),
    (u'Sports', u'sports'),
    (u'Websites', u'websites'),
)


def generate_categories(app=None):
    """
    Generate a list of categories for the optional `app` based on
    production categories names. If the `app` is not provided,
    the category will be created for a theme (old persona).

    """
    categories = []
    if app is None:  # This is a theme.
        type_ = ADDON_PERSONA
        application = None
        categories_choices = themes_categories
    else:
        type_ = ADDON_EXTENSION
        application = app.id
        categories_choices = addons_categories[app.short]

    for i, category_choice in enumerate(categories_choices):
        category, created = Category.objects.get_or_create(
            slug=category_choice[1],
            type=type_,
            application=application,
            defaults={
                'name': category_choice[0],
                'weight': i,
            })
        if created:
            generate_translations(category)
        categories.append(category)
    return categories
