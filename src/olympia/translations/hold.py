from threading import local

import django.dispatch

from django.core.signals import request_finished


_to_save = local()


def add_translation(*, instance, translation, field):
    """
    Queue a `translation` that needs to be saved for a particular `field` on
    `instance`.
    """
    if not hasattr(_to_save, 'translations'):
        _to_save.translations = {}
    key = make_key(instance)
    _to_save.translations.setdefault(key, [])
    _to_save.translations[key].append((field.name, translation))


def clean_translations(sender, **kwargs):
    """
    Removes all translations in the queue.
    """
    if hasattr(_to_save, 'translations'):
        _to_save.translations = {}


def make_key(obj):
    """Returns a key for this object."""
    return id(obj)


def save_translations(instance):
    """
    For a given instance, save all the translations in the queue and then
    clear them from the queue.
    """
    if not hasattr(_to_save, 'translations'):
        return

    key = make_key(instance)

    for field_name, translation in _to_save.translations.get(key, []):
        is_new = translation.autoid is None
        translation.save(force_insert=is_new, force_update=not is_new)
        translation_saved.send(
            sender=instance.__class__, instance=instance, field_name=field_name
        )

    if key in _to_save.translations:
        del _to_save.translations[key]


# Ensure that on request completion, we flush out any unsaved translations.
request_finished.connect(clean_translations, dispatch_uid='clean_translations')

translation_saved = django.dispatch.Signal()
