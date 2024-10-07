describe(__filename, () => {
  it('has gettext() function in static-build/ for local development', () => {
    const i18n_fr = require('../../../static-build/js/i18n/fr.js');
    expect(i18n_fr.django.gettext).toBeInstanceOf(Function);
  });

  it('has gettext() function and translations in site-static/ for production', () => {
    // Note: the actual path required in prod is not `fr.js`, but rather
    // fr.<hash>.js. But we don't know the hash without requiring some python.
    const i18n_fr = require('../../../site-static/js/i18n/fr.js');
    expect(i18n_fr.django.gettext).toBeInstanceOf(Function);
    expect(
      i18n_fr.django.catalog['There was an error uploading your file.'],
    ).toEqual('Une erreur est survenue pendant l’envoi de votre fichier.');
  });
});
