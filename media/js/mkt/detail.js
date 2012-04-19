(function() {
    function toggle($e) {
        // Toggle description + developer comments.
        $e.toggleClass('expanded').siblings('.collapse').toggleClass('show');
    }
    z.page.on('click', 'a.collapse', _pd(function() {
        toggle($(this));
    })).on('click', '.description', function(e) {
        if (!$(e.target).is('a')) {
            toggle($(this).find('a.collapse'));
        }
    });
})();
