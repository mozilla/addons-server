(function() {
    var $this;
    $('.devhub-form').on('click', '.toggles a', _pd(function() {
        $this = $(this);
        var $choices = $this.closest('td').find('.checkbox-choices input[type=checkbox]:not(:disabled)');
        if ($this.hasClass('all')) {
            $choices.attr('checked', true);
        } else {
            $choices.removeAttr('checked');
        }
    })).on('editLoaded.disableCheckboxes', function(e) {
        // Disable individual checkbox fields when we see them.
        // (Customizing Django's CheckboxSelectMultiple widget is stupid.)
        $('.checkbox-choices').each(function() {
            $this = $(this);
            var choices = JSON.parse($this.attr('data-disabled'));
            var selectors = _.map(choices, function(val) {
                return format('input[value="{0}"]', val);
            });
            $this.find(selectors.join(', ')).attr('disabled', true).removeAttr('checked');
        });
    });
})();
