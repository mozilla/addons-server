(function() {
    var els = $('.grid .mkt-tile');

    function fillBg(els) {
        _.each(els, function(el) {
            var tile = el.querySelector('[data-hue]');
            if (!tile) return;
            var hue = +tile.getAttribute('data-hue');
            // if (!hue) return;
            var canvas = el.querySelector('canvas') || document.createElement('canvas');
            var cs = window.getComputedStyle(el, null);
            var width = parseInt(cs.getPropertyValue('width'), 10);
            var height = parseInt(cs.getPropertyValue('height'), 10);
            canvas.width = width;
            canvas.height = height;
            var ctx = canvas.getContext('2d');
            var grad = ctx.createRadialGradient(width/2, height/2, 0, width/2, height/2, (width+height)/2.5);
            if (hue) {
                grad.addColorStop(0, "hsl(" + hue + ",100%,85%)");
                grad.addColorStop(1, "hsl(" + hue + ",75%,50%)");
            } else {
                grad.addColorStop(0, "hsl(0,0%,94%)");
                grad.addColorStop(1, "hsl(0,0%,80%)");
            }
            ctx.fillStyle = grad;
            ctx.fillRect(0,0,width,height);
            el.insertBefore(canvas, el.firstChild);
        });
    }

    fillBg(els);

    z.page.on('fragmentloaded', function() {
        var els = document.querySelectorAll('.grid .mkt-tile');
        if (els.length) {
            fillBg(els);
        }
    });
})();
