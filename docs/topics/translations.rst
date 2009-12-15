.. _translations:

============================
Translating Fields on Models
============================

The ``translations`` app defines a :class:`~translations.models.Translation`
model, but for the most part, you shouldn't have to use that directly.  When you
want to create a foreign key to the ``translations`` table, use
:class:`translations.fields.TranslatedField`.  This subclasses Django's
:class:`django.db.models.ForeignKey` to make it work with our special handling
of translation rows.

A minimal Addon model looks like this::

    import amo
    from translations.fields import TranslatedField

    class Addon(amo.ModelBase):
        name = TranslatedField()
        description = TranslatedField()

:class:`amo.ModelBase` inherits from
:class:`translations.fields.TranslatedFieldMixin`, which fetches all of a
model's translations during initialization.  It first tries to fetch strings for
the current locale, and then looks for any missing strings in the default
locale.  If you want to change this behavior, it should be enough to override
:meth:`_fetch_translations <translations.fields.TranslatedFieldMixin._fetch_translations>`.


Creating New Translations
-------------------------

If you need to create new
:class:`Translations <translations.models.Translation>` without the automagic
helpers behind :class:`~translations.fields.TranslatedField`, use
:meth:`Translation.new <translations.models.Translation.new>`.

.. automethod:: translations.models.Translation.new


``translations.fields``
-----------------------

.. module:: translations.fields

.. autoclass:: translations.fields.TranslatedField

.. autoclass:: translations.fields.TranslatedFieldMixin
    :members: _set_translated_fields, _fetch_translations


``translations.models``
-----------------------

.. module:: translations.models
.. autoclass:: translations.models.Translation
.. autoclass:: translations.models.TranslationSequence
