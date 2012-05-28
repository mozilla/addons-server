(function() {
    z.page.on('fragmentloaded', function() {
        var $nav = $('.tabnav');
        if ($nav.length) {
            // Clicking on "Popular" or "New" toggles its respective tab.
            $nav.on('click', '[data-show]', function() {
                var $this = $(this),
                    group = $this.data('show');

                // The previously selected tab + section are no longer "shown."
                z.page.find('[data-shown]').removeAttr('data-shown');

                // Mark the new section as "shown."
                z.page.find(format('[data-group={0}]', group)).attr('data-shown', true);

                // Mark the tab as "shown."
                $this.attr('data-shown', true);
            });
        }
    });
})();
