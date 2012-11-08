z.page.on('click', '.loadmore button', function(e) {
    // Get the button
    var button = $(this);
    // Get the container
    var swapEl = button.parents('.loadmore');
    // Show a loading indicator.
    swapEl.addClass('loading');
    swapEl.append('<div class="throbber">');
    // Grab the url to fetch the data from.
    var url = button.data('more-url');
    // Fetch the new content.
    $.get(url, function(d) {
        // Swap the container with the new content.
        swapEl.replaceWith($(d).find('.listing').html());
        z.page.trigger('updatecache');
        z.page.trigger('fragmentloaded');
    });
});