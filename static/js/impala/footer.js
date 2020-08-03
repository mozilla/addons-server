(function () {
  var $footer = $('#footer'),
    $page = $('#page'),
    $win = $(window);
  function stickyFooter() {
    // Stick the footer to the bottom when there's head(foot)room.
    $footer.toggleClass(
      'sticky',
      $win.height() - $footer.outerHeight() > $page.outerHeight(),
    );
  }
  stickyFooter();
  $win.resize(_.debounce(stickyFooter, 200));
})();

$(document).ready(function () {
  $(window).trigger('resize');
});
