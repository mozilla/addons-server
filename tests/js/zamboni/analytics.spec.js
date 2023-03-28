describe(__filename, () => {
  it('inserts script tags for both versions of GA', () => {
    document.body.innerHTML = '<script />';

    require('../../../static/js/zamboni/analytics.js');

    const scriptTags = document.getElementsByTagName('script');
    expect(scriptTags.length).toEqual(3);
    expect(scriptTags[0].src).toEqual(
      'https://www.googletagmanager.com/gtag/js?id=G-B9CY1C9VBC',
    );
    expect(scriptTags[1].src).toEqual(
      'https://www.google-analytics.com/analytics.js',
    );
  });

  it('does not insert script tags for GA when DNT is true', () => {
    window.doNotTrack = jest.fn().mockReturnValue('1');
    document.body.innerHTML = '<script />';

    require('../../../static/js/zamboni/analytics.js');

    const scriptTags = document.getElementsByTagName('script');
    expect(scriptTags.length).toEqual(1);
  });
});
