$(function() {
    $('#search-facets').delegate('li.facet', 'click', function() {
        var $this = $(this);
        if ($this.hasClass('active')) {
            $this.removeClass('active');
        } else {
            $this.closest('ul').find('.active').removeClass('active');
            $this.addClass('active');
        }
    }).delegate('li.facet a', 'click', function(e) {
        e.stopPropagation();
    });
});
