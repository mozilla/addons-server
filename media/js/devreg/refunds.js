$(function() {
    // TODO(davor): Add AJAJ support.

    var $nav = $('#refund-nav'),
        num_tabs = $nav.find('li').length,
        $list_items = $nav.find('li');

    $nav.delegate('a', 'click', _pd(function() {
        var $my_item = $(this).closest('li'),
            t_index = num_tabs - $my_item.nextAll().length + 1;

        $list_items.removeClass('active');
        $my_item.addClass('active');
        $('.tabcontent').addClass('hidden')
        $('.tabcontent:nth-child(' + t_index + ')').removeClass('hidden');
    }));
});
