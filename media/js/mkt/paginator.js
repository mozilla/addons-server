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
    var selector = swapEl.attr('data-sel');
    // Fetch the new content.
    $.get(url, function(d) {
        var node = document.createElement('div');
        node.innerHTML = d;
        // Swap the container with the new content.
        swapEl.replaceWith($(node).find(selector).html());
        z.page.trigger('fragmentloaded');
        z.page.trigger('updatecache');
    });
});