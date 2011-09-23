$(document).ready(function(){
    var payments = {
        setup: function() {
            this.sandbox = tests.createSandbox('#upsell-test');
            initPayments(this.sandbox);
        },
        teardown: function() {
            this.sandbox.remove();
        }
    };
    module('Payment form', payments);
    test('Upsell addon click', function() {
             this.sandbox.find("#id_free").focus();
             equal(this.sandbox.find("#id_do_upsell_1").attr("checked"),
                   "checked");
         });
    test('Upsell description click', function() {
             this.sandbox.find("#id_text").focus();
             equal(this.sandbox.find("#id_do_upsell_1").attr("checked"),
                   "checked");
         });
    });