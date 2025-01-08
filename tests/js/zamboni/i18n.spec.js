import '../../../static-build/js/i18n/fr.js';

describe(__filename, () => {
  it('has gettext() function in static-build/ for local development', async () => {
    expect(global.django.gettext).toBeInstanceOf(Function);
  });

  it('has gettext() function and translations in site-static/ for production', async () => {
    expect(global.django.gettext).toBeInstanceOf(Function);
    expect(
      global.django.catalog['There was an error uploading your file.'],
    ).toEqual('Une erreur est survenue pendant l’envoi de votre fichier.');
  });
});
