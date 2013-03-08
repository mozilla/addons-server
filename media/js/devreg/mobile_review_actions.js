(function() {
    // This is mobile-only.
    if (!$('body').hasClass('mobile')) return;

    var $actions = $('.review-flagged-actions'),
        newbtns = '<div class="keep">' + gettext('Keep review; remove flags') + '</div>';

    newbtns += '<div class="nuke">' + gettext('Delete review') + '</div>';
    newbtns += '<div class="skip active">' + gettext('Skip for now') + '</div>';

    var $newbtns = $(newbtns);

    function setActive($parent, $btn) {
        $parent.find('div').removeClass('active');
        $btn.addClass('active');
    }

    $actions.each(function(i, elm) {
        var $this = $(elm),
            $ul = $this.find('ul');

        $ul.hide();
        $this.append($newbtns);

        $this.find('.keep').click(function() {
            $ul.find('input[value=-1]')[0].checked = true;
            setActive($this, $(this));
        });
        $this.find('.nuke').click(function() {
            $ul.find('input[value=1]')[0].checked = true;
            setActive($this, $(this));
        });
        $this.find('.skip').click(function() {
            $ul.find('input[value=0]')[0].checked = true;
            setActive($this, $(this));
        });

        $this.removeClass('hidden');
    });
})();
