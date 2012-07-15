(function() {
    function toggle($e) {
        // Toggle description + developer comments.
        $e.toggleClass('expanded').closest('section').find('.collapse').toggleClass('show');
    }
    z.page.on('click', 'a.collapse', _pd(function() {
        toggle($(this));
    })).on('click', '.approval-pitch', _pd(function() {
        $('#preapproval-shortcut').submit();
    }));
})();
