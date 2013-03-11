/*
 * JavaScript helper for creating new rows from Django's formsets.
 *
 *
 * Example usage:
 *
 * <div id="formset">
 *   {% for form in formset %}
 *     <div class="formset">
 *       {{ form }}
 *     </div>
 *   {% endfor %}
  *   <div class="formset empty" style="display: none;">
 *     {{ formset.empty_form }}
 *   </div>
 *   <a href="#" id="add">{{ _('Add formset row') }}</a>
 * </div>
 * 
 * $('#formset').formset();
 * $('#add').on('click', function(evt) {
 *   $('#formset').formset('addRow');
 * });
 *
 *
 * Options:
 *
 * $().formset({
 *   'formsetClass': 'formset',  // Class indicating a formset row (empty or otherwise)
 *   'emptyClass': 'empty',  // Class indicating empty row
 *   'prefix': '__prefix__',  // Prefix indicating number of formset row
 *   'totalForms': '-TOTAL_FORMS',  // End of `name` attr of hidden field indicating total number of
 *                                  // forms (useful if you use multiple formsets in a single <form>)
 * })
 *  
 */

(function($) {

var methods = {

    init: function(options) {

        var $this = $(this);

        options = $.extend({
            emptyClass: 'empty',
            formsetClass: 'formset',
            prefix: '__prefix__',
            totalFormsName: '-TOTAL_FORMS'
        }, options);

        options = $.extend({
            emptySelector: format('.{0}.{1}', options.formsetClass, options.emptyClass),
            rowSelector: format('.{0}:not(.{1})', options.formsetClass, options.emptyClass)
        }, options);

        options = $.extend({
            rows: $this.children(options.rowSelector),
            empty: $this.children(options.emptySelector)
        }, options);

        options = $.extend({
            num: options.rows.length - 1,
            latestRow: options.rows.last(),
            totalForms: $this.closest('form').find('input[name$="' + options.totalFormsName + '"]')
        }, options);

        $this.data('options', options);

        return $this;

    },

    options: function() {
        return $(this).data('options');
    },

    addRow: function() { 

        var $this = $(this),
            options = $this.data('options'),
            $empty = options.empty,
            $copy = $empty.clone().removeClass(options.emptyClass),
            newNum = options.num + 1;

        // Update attributes containing options.prefix, updating with the
        // appropriate number.
        $.each(['id', 'for', 'name'], function(index, attr) {
            var attrSelector = format('[{0}*="{1}"]', attr, options.prefix),
                $hasAttr = $copy.find(attrSelector);
            $hasAttr.each(function(index, elem){
                var $elem = $(elem),
                    oldVal = $elem.attr(attr),
                    newVal = oldVal.replace(options.prefix, newNum);
                $elem.attr(attr, newVal);
            })
        });

        // Insert new row
        $copy.show().insertBefore($empty);

        // Update and save options
        options.rows = $this.find(options.rowSelector);
        options.num = newNum;
        options.latestRow = options.rows.last();
        options.totalForms.val(options.rows.length);
        $this.data('options', options);

        // Return self
        return $this;

    }

};

$.fn.formset = function(method) {

    if (methods[method]) {
        return methods[method].apply(this, Array.prototype.slice.call(arguments, 1));
    } else if (typeof method === 'object' || !method) {
        return methods.init.apply(this, arguments);
    } else {
        $.error('Method ' +  method + ' does not exist on $.formset');
    }

};

})(jQuery);
