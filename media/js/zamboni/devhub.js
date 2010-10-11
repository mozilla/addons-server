$(document).ready(function() {
    $(".more-actions-view-dropdown").popup(".more-actions-view", {
        width: 'inherit',
        offset: {x: 15},
        callback: function(obj) {
            return {pointTo: $(obj.click_target)};
        }
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

$("#author_list .blank .email-autocomplete, #user-form-template .email-autocomplete")
    .val("")
    .attr("placeholder", gettext("Enter a new author's email address"));

$(document).ready(function() {
    initAuthorFields();

    $("#id_has_eula").change(function (e) {
        if ($(this).attr("checked")) {
            $(".eula").show().removeClass("hidden");
        } else {
            $(".eula").hide();
        }
    });
    $("#id_has_priv").change(function (e) {
        if ($(this).attr("checked")) {
            $(".priv").show().removeClass("hidden");
        } else {
            $(".priv").hide();
        }
    });
    var other_val = $(".license-other").attr("data-val");
    $(".license").click(function (e) {
        if ($(this).val() == other_val) {
            $(".license-other").show().removeClass("hidden");
        } else {
            $(".license-other").hide();
        }
    });
});

function initAuthorFields() {
    var request = false,
        timeout = false,
        manager = $("#id_form-TOTAL_FORMS"),
        empty_form = $("#user-form-template").html().replace(/__prefix__/g, "{0}"),
        author_list = $("#author_list");
    author_list.sortable({
        items: ".author",
        handle: ".handle",
        containment: author_list,
        tolerance: "pointer",
        update: renumberAuthors
    });
    renumberAuthors();

    $("#author_list").delegate(".email-autocomplete", "keypress", validateUser)
    .delegate(".email-autocomplete", "keyup", validateUser)
    .delegate(".remove", "click", function (e) {
        e.preventDefault();
        var tgt = $(this),
            row = tgt.parents("li");
        if (author_list.children(".author:visible").length > 1) {
            if (row.hasClass("initial")) {
                row.find(".delete input").attr("checked", "checked");
                row.hide();
            } else {
                row.remove();
                manager.val(author_list.children(".author").length);
                renumberAuthors();
            }
        }
    });
    function renumberAuthors() {
        author_list.children(".author").each(function(i, el) {
            $(el).find(".position input").attr("value", i);
        });
    }
    function validateUser (e) {
        var tgt = $(this),
            row = tgt.parents("li"),
            numForms = manager.val();
        if (row.hasClass("blank")) {
            tgt.removeClass("placeholder")
               .attr("placeholder", undefined);
            row.removeClass("blank")
               .addClass("author");
            author_list.append(format(empty_form, [numForms]))
                       .sortable("refresh");
            author_list.find(".blank .email-autocomplete")
                       .placeholder();
            manager.val(author_list.children(".author").length);
            renumberAuthors();
        }
        if (tgt.val().length > 2) {
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(function () {
                tgt.addClass("ui-autocomplete-loading")
                   .removeClass("invalid")
                   .removeClass("valid");
                request = $.ajax({
                    url: tgt.attr("data-src"),
                    data: {q: tgt.val()},
                    success: function(data) {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("valid");
                    },
                    error: function() {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("invalid");
                    }
                });
            }, 500);
        }
    }
}
