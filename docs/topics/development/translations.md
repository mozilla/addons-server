(translations)=

# Translating Fields on Models

The _olympia.translations_ app defines a
_olympia.translations.models.Translation_ model, but for the most part, you
shouldn't have to use that directly. When you want to create a foreign key to
the _translations_ table, use
`olympia.translations.fields.TranslatedField`. This subclasses Django's
_django.db.models.ForeignKey_ to make it work with our special handling
of translation rows.

A minimal model with translations in addons-server would look like this:

```
from django.db import models

from olympia.amo.models import ModelBase
from olympia.translations.fields import TranslatedField, save_signal

class MyModel(ModelBase):
    description = TranslatedField()

models.signals.pre_save.connect(save_signal,
                                sender=MyModel,
                                dispatch_uid='mymodel_translations')
```

## How it works behind the scenes

As mentioned above, a _TranslatedField_ is actually a _ForeignKey_ to the
_translations_ table. However, to support multiple languages, we use a
special feature of MySQL allowing you to have a _ForeignKey_ pointing to
multiple rows.

### When querying

Our base manager has a __with_translations()_ method that is automatically
called when you instanciate a queryset. It does 2 things:

- Stick an extra lang=lang in the query to prevent query caching from returning
  objects in the wrong language
- Call _olympia.translations.transformers.get_trans()_ which does the black
  magic.

_get_trans()_ is called, and calls in turn
_olympia.translations.transformer.build_query()_ and builds a custom SQL
query. This query is the heart of the magic. For each field, it setups a join
on the translations table, trying to find a translation in the current language
(using `olympia.translation.get_language()`) and then in the language
returned by _get_fallback()_ on the instance (for addons, that's
`default_locale`; if the _get_fallback()_ method doesn't exist, it will
use `settings.LANGUAGE_CODE`, which should be _en-US_ in addons-server).

Only those 2 languages are considered, and a double join + _IF_ / _ELSE_ is
done every time, for each field.

This query is then ran on the slave (`get_trans()` gets a cursor using
`connections[multidb.get_replica()]`) to fetch the translations, and some
Translation objects are instantiated from the results and set on the
instance(s) of the original query.

To complete the mechanism, _TranslationDescriptor.__get___ returns the
`Translation`, and _Translations.__unicode___ returns the translated string
as you'd expect, making the whole thing transparent.

### When setting

Everytime you set a translated field to a string value,
_TranslationDescriptor_ ___set___ method is called. It determines which
method to call (because you can also assign a dict with multiple translations
in multiple languages at the same time). In this case, it calls
_translation_from_string()_ method, still on the "hidden"
_TranslationDescriptor_ instance. The current language is passed at this
point, using `olympia.translation_utils.get_language()`.

From there, _translation_from_string()_ figures out whether it's a new
translation of a field we had no translation for, a new translation of a
field we already had but in a new language, or an update to an existing
translation.

It instantiates a new _Translation_ object with the correct values if
necessary, or just updates the correct one. It then places that object in a
queue of Translation instances to be saved later.

When you eventually call `obj.save()`, the _pre_save_ signal is sent. If
you followed the example above, that means
_olympia.translations.fields.save_signal_ is then called, and it unqueues all
Translation objects and saves them. It's important to do this on _pre_save_
to prevent foreign key constraint errors.

### When deleting

Deleting all translations for a field is done using
`olympia.translations.models.delete_translation()`. It sets the field to
_NULL_ and then deletes all the attached translations.

Deleting a *specific* translation (like a translation in spanish, but keeping
the english one intact) is implemented but not recommended at the moment.
The reason why is twofold:

1. MySQL doesn't let you delete something that still has a FK pointing to it,
   even if there are other rows that match the FK. When you call _delete()_
   on a translation, if it was the last translation for that field, we set the
   FK to _NULL_ and delete the translation normally. However, if there were
   any other translations, instead we temporarily disable the constraints to
   let you delete just the one you want.
2. Remember how fetching works? If you deleted a translation that is part of
   the fallback, then when you fetch that object, depending on your locale
   you'll get an empty string for that field, even if there are _Translation_
   objects in other languages available!

For additional discussion on this topic, see
<https://bugzilla.mozilla.org/show_bug.cgi?id=902435>

### Ordering by a translated field

_olympia.translations.query.order_by_translation_ allows you to order a
_QuerySet_ by a translated field, honoring the current and fallback locales
like it's done when querying.
