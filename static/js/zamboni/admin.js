(function(){
    "use strict";

    // Add sphinx-like links to headings with ids.
    $(function(){
        var html = '<a class="headerlink" href="#{0}">&para;</a>';
        $(':-moz-any(h1,h2,h3,h4,h5,h6)[id]').each(function() {
          console.log(format(html, $(this).attr('id')));
          $(this).append(format(html, $(this).attr('id')));
        });
    });

    $(document).ready(function() {
        $('input.searchbar').each(function() {
            var $form = $(this).closest('form');
            $(this).autocomplete({
                minLength: 3,
                width: 300,
                source: function(request, response) {
                    $.getJSON($form.attr('data-search-url') + '?' + $form.serialize(),
                              response);
                },
                focus: function(event, ui) {
                    $(this).val(ui.item.label);
                    event.preventDefault();
                },
                select: function(event, ui) {
                    window.location = $form.attr('action') + '/' + ui.item.value;
                    event.preventDefault();
                }
            });
            $form.on('submit', _pd(function() {
                // Prevent just submitting the form because that takes you
                // to your page. TODO: do something clever with this.
            }));
        });

        // Recalculate Hash
        $('.recalc').click(_pd(function() {
            var $this = $(this);
            $this.html('Recalcing&hellip;');
            $.post($this.attr('href'), function(d) {
                if(d.success) {
                    $this.text('Done!');
                } else {
                    $this.text('Error :(');
                }
                setTimeout(function() {
                    $this.text('Recalc Hash');
                }, 2000);
            });
        }));
    });
    $('#id_start, #id_end').datepicker({ dateFormat: 'yy-mm-dd' });
})();
