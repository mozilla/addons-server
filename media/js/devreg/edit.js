(function() {
    $('.devhub-form').on('click', '.toggles a', _pd(function() {
        var $this = $(this),
            $choices = $this.closest('td').find('.checkbox-choices input[type=checkbox]');
        if ($this.hasClass('all')) {
            $choices.attr('checked', true);
        } else {
            $choices.removeAttr('checked');
        }
    }));
})();
