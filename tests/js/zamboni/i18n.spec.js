import { vi } from 'vitest';

const importFr = (dir) => import(`../../../${dir}/js/i18n/fr.js`);

describe('i18n', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('has gettext() function in static-build/ for local development', async () => {
    await importFr('static-build');
    expect(global.django.gettext).toBeInstanceOf(Function);
  });

  it('has gettext() function and translations in site-static/ for production', async () => {
    await importFr('site-static');
    expect(global.django.gettext).toBeInstanceOf(Function);
    expect(
      global.django.catalog['There was an error uploading your file.'],
    ).toEqual('Une erreur est survenue pendant l’envoi de votre fichier.');
  });
});
