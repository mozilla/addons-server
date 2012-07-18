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

    import amo.models
    from translations.fields import TranslatedField

    class Addon(amo.models.ModelBase):
        name = TranslatedField()
        description = TranslatedField()
