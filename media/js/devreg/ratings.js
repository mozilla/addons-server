/* IARC content ratings. */
define('iarc-ratings', [], function() {
    var $editPage = $('#ratings-edit');
    var $summaryPage = $('#ratings-summary');

    $('a.toggle-ratings-page').click(function() {
        $editPage.add($summaryPage).toggle();

        if ($('#ratings-edit:visible').length !== 0) {
            window.location.hash = 'edit';
        } else {
            window.location.hash = '';
        }
    });

    if (window.location.hash === '#edit' && $('tbody tr', $summaryPage).length !== 0) {
        // Don't show edit page unless the summary table has stuff in it
        // (i.e. unless the app has content ratings).
        $editPage.show();
        $summaryPage.hide();
    }
});
