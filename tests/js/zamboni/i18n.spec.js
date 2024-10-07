describe(__filename, () => {
  it('has translations in french', () => {
    // We require the output from generate_jsi18n_files (which should live in
    // static-build/ before getting picked up by collectstatic). It should
    // contain not only gettext() function definition, some translations from
    // django, but also our own, if it was called by the docker build process
    // in the right order, after locales have been built.
    const i18n_fr = require('../../../static-build/js/i18n/fr.js');
    expect(i18n_fr.django.gettext).toBeInstanceOf(Function);
    expect(
      i18n_fr.django.catalog['There was an error uploading your file.'],
    ).toEqual('Une erreur est survenue pendant l’envoi de votre fichier.');
  });
});
