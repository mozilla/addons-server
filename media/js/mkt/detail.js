(function() {
    z.page.on('click', '#product-rating-status .toggle', _pd(function() {
        // Show/hide scary content-rating disclaimers to developers.
        $(this).closest('.toggle').siblings('div').toggleClass('hidden');
    }));

    z.page.on('click', '.show-toggle', _pd(function() {
        var $this = $(this),
            newTxt = $this.attr('data-toggle-text');
        // Toggle "more..." or "less..." text.
        $this.attr('data-toggle-text', $this.text());
        $this.text(newTxt);
        // Toggle description + developer comments.
        $this.closest('.blurbs').find('.collapsed').toggle();
    })).on('click', '.approval-pitch', _pd(function() {
        $('#preapproval-shortcut').submit();
    }));

    // When I click on the icon, append `#id=<id>` to the URL.
    z.page.on('click', '.product-details .icon', _pd(function(e) {
        window.location.hash = 'id=' + $('.product').data('product')['id'];
        e.stopPropagation();
    }));

    z.page.on('fragmentloaded', function() {
        var reviews = $('.detail .reviews li');
        if (reviews.length < 3) return;

        for (var i=0; i<reviews.length-2; i+=2) {
            var hgt = Math.max(reviews.eq(i).find('.review-inner').height(),
                               reviews.eq(i+1).find('.review-inner').height());
            reviews.eq(i).find('.review-inner').height(hgt);
            reviews.eq(i+1).find('.review-inner').height(hgt);
        }
    });
})();
