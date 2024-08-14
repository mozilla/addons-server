# Localization and Internationalization

Localization and internationalization are important aspects of the **addons-server** project, ensuring that the application can support multiple languages and locales. This section covers the key concepts and processes for managing localization and internationalization.

## Locale Management

Locale management involves compiling and managing translation files. The **addons-server** project uses a structured approach to handle localization files efficiently.

1. **Compiling Locales**:
   - The Makefile provides commands to compile locale files, ensuring that translations are up-to-date.
   - Use the following command to compile locales:

     ```sh
     make compile_locales
     ```

2. **Managing Locale Files**:
   - Locale files are typically stored in the `locale` directory within the project.
   - The project structure ensures that all locale files are organized and easily accessible for updates and maintenance.

## Adding New Translations

We write the english translations of our strings directly in the code, using the `gettext` function. For example:

```python
from django.utils.translation import gettext_lazy as _

def my_view(request):
    output = _('Welcome to my site.')
    return HttpResponse(output)
```

When developing locally you should not really need to do anything special to see the translations. The `gettext` function will return the string as is if it can't find a translation for it. In CI translation strings are automatically extracted and uploaded to Pontoon for translation.

## Translation Management

Translation management involves handling translation strings and merging them as needed. The **addons-server** project follows best practices to ensure that translations are accurate and consistent.

1. **Handling Translation Strings**:
   - Translation strings are extracted from the source code and stored in `.po` files.
   - The `.po` file format is used to manage locale strings, providing a standard way to handle translations.

2. **Merging Translation Strings**:
   - To extract new locales from the codebase, use the following command:

     ```sh
     make extract_locales
     ```

   - This command scans the codebase and updates the `.po` files with new or changed translation strings.
   - After extraction, scripts are used to merge new or updated translation strings into the existing locale files.
   - This process ensures that all translations are properly integrated and maintained.

## Additional Tools and Practices

1. **Pontoon**:
   - The **addons-server** project uses Pontoon, Mozilla's localization service, to manage translations.
   - Pontoon provides an interface for translators to contribute translations and review changes, ensuring high-quality localization.

2. **.po File Format**:
   - The `.po` file format is a widely used standard for managing translation strings.
   - It allows for easy editing and updating of translations, facilitating collaboration among translators.

## Translating Fields on Models

The `olympia.translations` app defines a `olympia.translations.models.Translation` model, but for the most part, you shouldn't have to use that directly. When you want to create a foreign key to the `translations` table, use `olympia.translations.fields.TranslatedField`. This subclasses Django's `django.db.models.ForeignKey` to make it work with our special handling of translation rows.

### Minimal Model Example

A minimal model with translations in addons-server would look like this:

```python
from django.db import models

from olympia.amo.models import ModelBase
from olympia.translations.fields import TranslatedField, save_signal

class MyModel(ModelBase):
    description = TranslatedField()

models.signals.pre_save.connect(save_signal,
                                sender=MyModel,
                                dispatch_uid='mymodel_translations')
```

### How It Works Behind the Scenes

A `TranslatedField` is actually a `ForeignKey` to the `translations` table. To support multiple languages, we use a special feature of MySQL allowing a `ForeignKey` to point to multiple rows.

#### When Querying

Our base manager has a `_with_translations()` method that is automatically called when you instantiate a queryset. It does two things:

- Adds an extra `lang=lang` in the query to prevent query caching from returning objects in the wrong language.
- Calls `olympia.translations.transformers.get_trans()` which builds a custom SQL query to fetch translations in the current language and fallback language.

This custom query ensures that only the specified languages are considered and uses a double join with `IF`/`ELSE` for each field. The results are fetched using a slave database connection to improve performance.

#### When Setting

Every time you set a translated field to a string value, the `TranslationDescriptor` `__set__` method is called. It determines whether it's a new translation or an update to an existing translation and updates the relevant `Translation` objects accordingly. These objects are queued for saving, which happens on the `pre_save` signal to avoid foreign key constraint errors.

#### When Deleting

Deleting all translations for a field is done using `olympia.translations.models.delete_translation()`, which sets the field to `NULL` and deletes all attached translations. Deleting a specific translation is possible but not recommended due to potential issues with fallback languages and foreign key constraints.

### Ordering by a Translated Field

`olympia.translations.query.order_by_translation` allows you to order a `QuerySet` by a translated field, honoring the current and fallback locales like when querying.

By following these practices, the **addons-server** project ensures that the application can support multiple languages and locales effectively. For more detailed instructions, refer to the project's Makefile and locale management scripts in the repository.
