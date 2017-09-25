$(function() {
    initListingCompat();

    $('.theme-grid .hovercard.theme').each(function() {
        var $this = $(this);
        if ($this.find('.acr-override').length) {
            $this.addClass('acr');
        } else if ($this.find('.concealed').length == $this.find('.button').length) {
            $this.addClass('incompatible');
            // L10n: {0} is an app name.
            var msg = format(gettext('This theme is incompatible with your version of {0}'),
                             [z.appName]);
            $this.append(format('<span class="notavail">{0}</span>', msg));
        }
    });


    // Make this row appear 'static' so the installation buttons and pop-ups
    // stay open when hovering outside the item row.
    $(document.body).on('newStatic', function() {
        $('.install-note:visible').closest('.item').addClass('static');
    }).on('closeStatic', function() {
        $('.item.static').removeClass('static');
    });
});


function initListingCompat(domContext) {
    domContext = domContext || document.body;
    // Mark incompatible add-ons on listing pages unless marked with ignore.
    $('.listing .item.addon', domContext).each(function() {
        var $this = $(this);
        var isIncompatible = (!$this.hasClass('ignore-compatibility') &&
          ($this.find('.concealed').length == $this.find('.button').length ||
           $this.find('button.not-available').length)
        );

        if ($this.find('.acr-override').length) {
            $this.addClass('acr');
        } else if (isIncompatible) {
          $this.addClass('incompatible');
        }
    });
}
