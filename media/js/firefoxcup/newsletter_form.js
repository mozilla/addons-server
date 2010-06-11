// set up newsletter signup widget
$(document).ready(function() {

    $("#email").show()
    var error = $('#error-box');

    var errorMessages = {
        'email':         'Whoops! Be sure to enter a valid email address.',
        'privacy':       'Please read the Mozilla Privacy Policy and agree ' +
                         'by checking the box.',
        'email-privacy': 'Please enter your email address and review the ' +
                         'Mozilla Privacy Policy.'
    }

    function showError(message)
    {
        error.empty();
        error.append(message);
        error.fadeIn(); 
    }

    function hideError()
    {
        error.empty();
        error.fadeOut();
    }

    function validateEmail(email)
    {
        return /^([\w\-.+])+@([\w\-.])+\.[A-Za-z]{2,4}$/.test(email);
    }

    function validateForm(formData, jqForm, options)
    {
        form = jqForm[0];

        var valid = true;
        
        var privacy = form.privacy.checked;
        var email = validateEmail(form.email.value);

        if (email) {
            $(form.email).removeClass('form-error');
        } else {
            $(form.email).addClass('form-error');
            valid = false;
        }

        if (privacy) {
            $(form.privacy).parent().removeClass('form-error');
        } else {
            $(form.privacy).parent().addClass('form-error');
            valid = false;
        }

        // show or hide error messages
        if (!email && !privacy) {
            showError(errorMessages['email-privacy']);
        } else if (!email) {
            showError(errorMessages['email']);
        } else if (!privacy) {
            showError(errorMessages['privacy']);
        } else {
            hideError();
        }

        return valid;
    }

    $('#email-start').click(function(e) {
        e.preventDefault();
        $(this).fadeOut(function () {
            $('#email-form').fadeIn();
        });
    });

    $("#email-form form").ajaxForm({
        beforeSubmit: validateForm,
        type: 'POST',
        success: function () {
            $("#email-form").fadeOut(function () {
                $("#email-finish").fadeIn();
            })
        }
    });
});
