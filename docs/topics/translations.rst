.. _translations:

============================
Translating Fields on Models
============================

The ``translations`` app defines a :class:`~translations.models.Translation`
model, but for the most part, you shouldn't have to use that directly. When you
want to create a foreign key to the ``translations`` table, use
:class:`translations.fields.TranslatedField`. This subclasses Django's
:class:`django.db.models.ForeignKey` to make it work with our special handling
of translation rows.

A minimal model with translations in zamboni would look like this::

    from django.db import models

    import amo.models
    import translations.fields

    class MyModel(amo.models.ModelBase):
        description = translations.fieldsTranslatedField()

    models.signals.pre_save.connect(translations.fields.save_signal,
                                    sender=MyModel,
                                    dispatch_uid='mymodel_translations')

How it works behind the scenes
==============================

As mentioned above, a ``TranslatedField`` is actually a ``ForeignKey`` to the
``translations`` table. However, to support multiple languages, we use a 
special feature of MySQL allowing you to have a ``ForeignKey`` pointing to 
multiple rows.

When querying
-------------
Our base manager has a ``_with_translations()`` method that is automatically 
called when you instanciate a queryset. It does 2 things:

- Stick an extra lang=lang in the query to prevent query caching from returning 
  objects in the wrong language
- Call ``translations.transformers.get_trans()`` which does the black magic.

``get_trans()`` is called, and calls in turn ``translations.transformer.build_query()`` 
and builds a custom SQL query. This query is the heart of the magic. For each 
field, it setups a join on the translations table, trying to find a translation
in the current language (using ``translation.get_language()``) and then in the
language returned by ``get_fallback()`` on the instance (for addons, that's 
``default_locale``; if the ``get_fallback()`` method doesn't exist, it will
use ``settings.LANGUAGE_CODE``, which should be ``en-US`` in zamboni).

Only those 2 languages are considered, and a double join + ``IF`` / ``ELSE`` is
done every time, for each field.

This query is then ran on the slave (``get_trans()`` gets a cursor using
``connections[multidb.get_slave()]``) to fetch the translations, and some 
Translation objects are instanciated from the results and set on the 
instance(s) of the original query. 

To complete the mechanism, ``TranslationDescriptor.__get__`` returns the 
``Translation``, and ``Translations.__unicode__`` returns the translated string
as you'd except, making the whole thing transparent.

When setting
------------
Everytime you set a translated field to a string value, ``TranslationDescriptor``
``__set__`` method is called. It determines what method to call (because you 
can also assign a dict with multiple translations in multiple languages at the 
same time). In this case, it calls ``translation_from_string()`` method, still 
on the "hidden" ``TranslationDescriptor`` instance. The current language is 
passed at this point, using ``translation_utils.get_language()``.

From there, ``translation_from_string()`` figures out whether it's a new 
translation of a field we had no translation for, or a new translation of a 
field we already had but in a new language, or an update to an existing 
translation. 

It instantiates a new ``Translation`` object with the correct values if 
necessary, or just updates the correct one. It then places that object in a 
queue of Translation instances to be saved later.

When you eventually call ``obj.save()``, the ``pre_save`` signal is sent. If
you followed the example above, that means ``translations.fields.save_signal``
is then called, and in unqueues all Translation objects and saves them. It's
important to do this on ``pre_save`` to prevent foreign key constraint errors.

When deleting
-------------
Deleting all translations for a field is done using ``delete_translation()``. 
It sets the field to ``NULL`` and then deletes all the attached translations.

Deleting a *specific* translation (like a translation in spanish, but keeping
the english one intact) is implemented but not recommended at the moment.
The reason why is twofold: 

1. MySQL doesn't let you delete something that still has a FK pointing to it,
   even if there are other rows that match the FK. When you call ``delete()`` 
   on a translation, if it was the last translation for that field, we set the
   FK to ``NULL`` and delete the translation normally. However, if there were 
   any other translations, instead we temporarily disable the constraints to 
   let you delete just the one you want.
2. Remember how fetching works ? If you deleted a translation that is part of 
   the fallback, then when you fetch that object, depending on your locale 
   you'll get an empty string for that field, even if there are ``Translation``
   objects in other languages available !

For additional discussion on this topic, see https://bugzilla.mozilla.org/show_bug.cgi?id=902435

Additional tricks
-----------------
In addition to the above, ``apps/translations/__init__.py`` monkeypatches 
django to bypass errors thrown because we have a ``ForeignKey`` pointing to 
multiple rows.

Also, you might be interested into ``translations.query.order_by_translation``.
Like the name suggests, it allows you to order a ``QuerySet`` by a translated
field, honoring the current and fallback locales like it's done when querying.
