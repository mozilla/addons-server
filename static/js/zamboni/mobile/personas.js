$(document).ready(function() {
    var personas = $('.persona-preview');
    if (!personas.length) return;
    personas.previewPersona();
});


/**
 * Binds Personas preview events to the element.
 * Click - bubbles up PreviewPersona
 * Click again - bubbles up ResetPersona
 **/
$.fn.previewPersona = function(o) {
    if (!$.hasPersonas()) {
        return;
    }
    o = $.extend({
        activeClass:   'persona-hover',
        disabledClass: 'persona-installed'
    }, o || {});
    $(this).click(function(e) {
        var $outer = $(this).closest('.persona-previewer'),
            $persona = $outer.find('.persona');
        if ($persona.hasClass(o.disabledClass)) {
            return;
        }
        var mp = new MobilePersona(this),
            states = mp.states();
        if ($persona.hasClass(o.activeClass)) {
            // Hide persona.
            $persona.removeClass(o.activeClass);
            dispatchPersonaEvent('ResetPersona', e.target,
                states.cancelled);
        } else {
            // Hide other active personas.
            $('.' + o.activeClass).each(function() {
                $(this).find('[data-browsertheme]').trigger('click');
            });
            // Load persona.
            $persona.addClass(o.activeClass);
            states.loading();
            dispatchPersonaEvent('PreviewPersona', e.target, states.previewing);
        }
    });
};


/* Should be called on an anchor. */
$.fn.personasButton = function(trigger, callback) {
    $(this).closest('.persona').click(function(e) {
        dispatchPersonaEvent('SelectPersona', e.currentTarget, callback);
        return false;
    });
};
