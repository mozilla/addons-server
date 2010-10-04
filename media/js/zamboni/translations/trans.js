(function($) {

/* These match the widgets generated in Python. */
var fragment = 'trans_{name}_{lang}';
var tab = template('<li><a href="#' + fragment + '" ' +
                            'title="{language}">{lang}</a></li>');
var trans = template('<div class="transbox">' +
                       '<textarea id="' + fragment + '" '+
                                 'data-locale="{lang}" ' +
                                 'name="{name}_{lang}">' +
                       '{content}</textarea></div>');
var remove = template('<input type="hidden" ' +
                               'name="{name}_{lang}_delete">')


/* Add a new locale to a translation box. */
var addLocale = function(transbox) {
    var field = transbox.attr('data-field');

    function updateLocaleSelection() {
        var select = transbox.find('.transbox-new select');
        var opts = select.find('option:not([disabled])')
        select.attr('selectedIndex', opts[0].index);
    };

    return function(e) {
        e.preventDefault();
        var opt = transbox.find('.transbox-new option:selected');
        var d = {
            name: field,
            lang: opt.val(),
            language: opt.attr('title'),
            content: ''
        };

        // Mark as taken.
        opt.attr('disabled', 'disabled');

        // Add tab.
        transbox.find('li a.add').parent().before(tab(d));

        // Add textarea.
        transbox.find('.transbox:last').after(trans(d));

        // Switch to textarea.
        transbox[0].tab.reset().select('#' + format(fragment, d));

        // Find a non-disabled locale.
        updateLocaleSelection();
    };
};

/* Remove a locale from transbox, mark it for deletion. */
var deleteLocale = function(transbox) {
    var field = transbox.attr('data-field');

    return function(e) {
        e.preventDefault();
        // Don't delete the add-locale tab or the only locale..
        // If there's one locale, there's 2 tabs: the locale and add tab.
        if (transbox.find('.tab.tab-selected .add').length ||
            transbox.find('.tab').length == 2) {
            return;
        }

        var locale = transbox.find('.tab-panel.tab-selected').attr('data-locale');
        // Add the hidden removal input.
        transbox.append(remove({name: field, lang: locale}));


        // Remove the locale and update the tabs.
        transbox.find('.tab-selected').remove();
        transbox[0].tab.reset().select();

        // Enable the locale.
        transbox.find('.transbox-new option[value="' + locale + '"]').attr('disabled', '');
    };
};


$.fn.transbox = function() {
    this.each(function() {
        $this = $(this);
        $this.find('button.add').click(addLocale($this));
        $this.find('button.delete').click(deleteLocale($this));
        $this.bind('tabselect', function(e, data) {
            $(data.panel).focus();
        });
    });
    return this;
};

})(jQuery);
