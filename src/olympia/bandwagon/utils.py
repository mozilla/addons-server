import waffle
from six import text_type

from olympia.lib.akismet.models import AkismetReport
from olympia.translations.models import Translation


def get_collection_akismet_reports(collection, user, user_agent, referrer,
                                   data=None):
    if not waffle.switch_is_active('akismet-spam-check'):
        return []
    properties = ('name', 'description')

    if not data:
        return []  # bail early if no data to skip Translation lookups
    translation_ids_gen = (
        getattr(collection, prop + '_id', None) for prop in properties)
    translation_ids = [id_ for id_ in translation_ids_gen if id_]
    # Just get all the values together to make it simplier
    existing_data = {
        text_type(value)
        for value in Translation.objects.filter(id__in=translation_ids)}
    reports = []
    for prop in properties:
        locales = data.get(prop)
        if not locales:
            continue
        if isinstance(locales, dict):
            # Avoid spam checking the same value more than once by using a set.
            locale_values = set(locales.values())
        else:
            # It's not a localized dict, it's a flat string; wrap it anyway.
            locale_values = {locales}
        for comment in locale_values:
            if not comment or comment in existing_data:
                # We don't want to submit empty or unchanged content
                continue
            reports.append(AkismetReport.create_for_collection(
                collection=collection,
                user=user,
                property_name=prop,
                property_value=comment,
                user_agent=user_agent,
                referrer=referrer))
    return reports
