$(document).ready(function() {
    $(".more-actions-view-dropdown").popup(".more-actions-view", {
        width: 'inherit',
        offset: {x: 15},
        callback: function(obj) {
            return {pointTo: $(obj.click_target)};
        }
    });
});
