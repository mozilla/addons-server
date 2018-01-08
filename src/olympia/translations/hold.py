from threading import local

from django.core.signals import request_finished


_to_save = local()


def add_translation(key, translation):
    """
    Queue a translation that needs to be saved for a particular object. To
    generate the key, call make_key.
    """
    if not hasattr(_to_save, 'translations'):
        _to_save.translations = {}

    _to_save.translations.setdefault(key, [])
    _to_save.translations[key].append(translation)


def clean_translations(sender, **kwargs):
    """
    Removes all translations in the queue.
    """
    if hasattr(_to_save, 'translations'):
        _to_save.translations = {}


def make_key(obj):
    """Returns a key for this object."""
    return id(obj)


def save_translations(key):
    """
    For a given key, save all the translations. The key is used to ensure that
    we only save the translations for the given object (and not all of them).
    Once saved, they will be deleted.
    """
    if not hasattr(_to_save, 'translations'):
        return

    for trans in _to_save.translations.get(key, []):
        is_new = trans.autoid is None
        trans.save(force_insert=is_new, force_update=not is_new)

    if key in _to_save.translations:
        del _to_save.translations[key]


# Ensure that on request completion, we flush out any unsaved translations.
request_finished.connect(clean_translations, dispatch_uid='clean_translations')
