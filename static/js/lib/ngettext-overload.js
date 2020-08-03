// Overload the ngettext function provided by django to fall-back
// to the provided string if a translation is missing.
// TODO: Remove this once we upgrade to a version of Django that contains
// the fix for https://code.djangoproject.com/ticket/27418
if (
  window.ngettext &&
  django &&
  django.ngettext &&
  django.catalog &&
  django.pluralidx
) {
  django.ngettext = function (singular, plural, count) {
    var value = django.catalog[singular];
    var translation;
    if (typeof value !== 'undefined') {
      translation = value[django.pluralidx(count)];
      if (translation && translation.length > 0) {
        return translation;
      }
    }
    return count == 1 ? singular : plural;
  };
  window.ngettext = django.ngettext;
}
