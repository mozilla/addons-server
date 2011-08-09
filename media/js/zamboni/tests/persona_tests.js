$(document).ready(function() {

    var personaFixture = {
        setup: function() {
            this.sandbox = tests.createSandbox('#personas');
            initLicense();
        },
        teardown: function() {
            this.sandbox.remove();
        },
        selectRadio: function(name, value) {
            var suite = this.sandbox;
            $('input[name=' + name + ']', suite).val(value);
            $('input[name=' + name + '][value=' + value + ']', suite)
                .attr('checked', true).trigger('change');
        }
    };

    module('Personas', personaFixture);

    test('License Chooser', function() {
        var that = this,
            suite = that.sandbox;
        function ccTest(values, licenseName, licenseId) {
            that.selectRadio('cc-attrib', values[0]);
            if (values.length > 1) {
                that.selectRadio('cc-noncom', values[1]);
                if (values.length > 2) {
                    that.selectRadio('cc-noderiv', values[2]);
                }
            }
            equals($('#cc-license', suite).text(), licenseName);
            equals(parseInt($('#id_license', suite).val()), licenseId);
        }
        ccTest([0],       'Creative Commons Attribution 3.0', 9);
        ccTest([0, 0],    'Creative Commons Attribution 3.0', 9);
        ccTest([0, 0, 0], 'Creative Commons Attribution 3.0', 9);
        ccTest([0, 0, 0], 'Creative Commons Attribution 3.0', 9);
        ccTest([0, 0, 1], 'Creative Commons Attribution-ShareAlike 3.0', 13);
        ccTest([0, 0, 2], 'Creative Commons Attribution-NoDerivs 3.0', 12);
        ccTest([0, 1, 0], 'Creative Commons Attribution-NonCommercial 3.0', 10);
        ccTest([0, 1, 1], 'Creative Commons Attribution-NonCommercial-Share Alike 3.0', 8);
        ccTest([0, 1, 2], 'Creative Commons Attribution-NonCommercial-NoDerivs 3.0', 11);
        ccTest([1],       'All Rights Reserved', 7);
        ccTest([1, 0],    'All Rights Reserved', 7);
        ccTest([1, 0, 0], 'All Rights Reserved', 7);
    });

});
