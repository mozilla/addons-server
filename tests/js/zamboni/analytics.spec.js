import { insertAnalyticsScript } from '../../../static/js/zamboni/analytics';

describe(__filename, () => {
  beforeEach(() => {
    document.body.innerHTML = '<script />';
  });

  it('inserts script tags for both versions of GA', async () => {
    insertAnalyticsScript();

    const scriptTags = document.getElementsByTagName('script');
    expect(scriptTags.length).toEqual(3);
    expect(scriptTags[0].src).toEqual(
      'https://www.googletagmanager.com/gtag/js?id=G-B9CY1C9VBC',
    );
    expect(scriptTags[1].src).toEqual(
      'https://www.google-analytics.com/analytics.js',
    );
  });

  it('does not insert script tags for GA when DNT is true', async () => {
    // set do not track to true
    insertAnalyticsScript(true);

    const scriptTags = document.getElementsByTagName('script');
    expect(scriptTags.length).toEqual(1);
  });
});
