$(document).ready(function() {
    $(".more-actions-view-dropdown").popup(".more-actions-view", {
        width: 'inherit',
        offset: {x: 15},
        callback: function(obj) {
            return {pointTo: $(obj.click_target)};
        }
    });

    $('#edit-addon').delegate('h3 a', 'click', function(e){
        e.preventDefault();

        parent_div = $(this).closest('.edit-addon-section');
        a = $(this);

        (function(parent_div, a){
            parent_div.load($(a).attr('href'), addonFormSubmit);
        })(parent_div, a);

        return false;
    });

    $('.addon-edit-cancel').live('click', function(){
        parent_div = $(this).closest('.edit-addon-section');
        parent_div.load($(this).attr('href'));
        return false;
    });


});

function addonFormSubmit() {
    parent_div = $(this);

    (function(parent_div){
        $('form', parent_div).submit(function(){
        $.post($(parent_div).find('form').attr('action'),
                $(this).serialize(), function(d){
                    $(parent_div).html(d).each(addonFormSubmit);
                });
            return false;
        });
    })(parent_div);
}
