from olympia.addons.models import Category
from olympia.constants.categories import CATEGORIES


def generate_categories(app=None, type=None):
    """
    Generate a list of categories for the given `app` and `type` based on
    categories constants.
    """
    categories = []
    categories_choices = CATEGORIES[app.id][type]
    for category_choice in categories_choices.values():
        defaults = {
            'slug': category_choice.slug,
            'db_name': unicode(category_choice.name),
            'application': app.id,
            'misc': category_choice.misc,
            'type': type,
            'weight': category_choice.weight,
        }
        category, created = Category.objects.get_or_create(
            id=category_choice.id, defaults=defaults
        )
        if not created:
            category.db_name = defaults.pop('db_name')
            category.__dict__.update(**defaults)
            category.save()
        categories.append(category)
    return categories
