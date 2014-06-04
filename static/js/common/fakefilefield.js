/*
 * jQuery plugin that provides hooks for making more usable + stylable
 * <input type="file" />s.
 * 
 * Usage:
 *
 * <div class="filefield">
 *   <input type="file" />
 *   <button data-fileinput-fake>Choose Image</button>
 * </div>
 *
 * $('.filefield').fakeFileField();
 * 
 * Anything matching input[type="file"] is hidden, and when anything marked
 * with data-fileinput-fake (or its children) is interacted with, the default
 * event is prevented and the true file input is clicked.
 * 
 * If data-fileinput-fake or any of its children are a text input, the value
 * of the real input is copied to that input on load/change.
 */

(function($) {

$.fn.fakeFileField = function() {

    return $.each(this, function(index, element){

        var $this = $(this),
            $parent = $this.parent(),
            $fake = $this.children('[data-fileinput-fake]'),
            $fakeText = $fake.find('input[type="text"]'),
            $real = $this.children('input[type="file"]'),
            realValue = $real.val();

        // Hide the real, show the fake.
        $fake.show();
        $real.hide();

        // When clicking on any of the fake elements, pretend like
        // the real input was clicked.
        $fake.find('*').add($fake).on('click', function(evt){
            evt.preventDefault();
            evt.stopPropagation();
            $real.click();
            $(this).blur();
        });

        // Copy the value from the real input to the fake one,
        // for visual consistency.
        if (realValue){
            $fakeText.val(realValue);
        }
        $real.on('change', function(evt) {
            $fakeText.val($(this).val());
        });

    });

};

})(jQuery);
