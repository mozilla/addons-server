google.load('search', '1', { language: $('html').attr('lang') });
google.setOnLoadCallback(function () {
  var qry = $('.header-search input[name="q"]'),
    opt = new google.search.DrawOptions();

  opt.setInput(qry.get(0));
  sc = new google.search.CustomSearchControl(
    '007182852441266509516:fnsg3w7luc4',
  );
  sc.setNoResultsString(gettext('No results found.'));
  sc.setSearchStartingCallback(null, function (sc, searcher, qry) {
    sc.maxResultCount = 0;
  });

  sc.setSearchCompleteCallback(null, function (sc, searcher) {
    if (searcher.results.length) {
      var cur = searcher.cursor,
        total = parseInt(cur.estimatedResultCount, 10);
      if (total > sc.maxResultCount) {
        sc.maxResultCount = total;
        $('#cse').show();
        window.scroll(0, 0);
      }
    } else {
      $('#resultcount').hide();
      $('#no-devsearch-results').show();
    }
    $(window).resize();
  });

  $('#cse').hide();
  sc.draw('cse', opt);
  sc.execute();

  if (!qry.val()) {
    $('#resultcount').show();
  }

  $('#searchbox').submit(
    _pd(function (e) {
      sc.execute();
    }),
  );
}, true);
