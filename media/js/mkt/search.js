(function() {
    $('#search-facets').delegate('li.facet', 'click', function(e) {
        var $this = $(this);
        if ($this.hasClass('active')) {
            if ($(e.target).is('a')) {
                return;
            }
            $this.removeClass('active');
        } else {
            $this.closest('ul').find('.active').removeClass('active');
            $this.addClass('active');
        }
    });
})();
