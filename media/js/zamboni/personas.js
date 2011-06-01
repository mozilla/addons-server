$(document).ready(function() {
    var personas = $('.persona-preview');
    if (!personas.length) return;
    personas.previewPersona();
});


/**
 * Binds Personas preview events to the element.
 * Click - bubbles up ResetPersona event
 * Mouseenter - bubbles up PreviewPersona
 * Mouseleave - bubbles up ResetPersona
 **/
$.fn.previewPersona = function(o) {
    if (!$.hasPersonas()) {
        return;
    }
    o = $.extend({
        resetOnClick: true,
        activeClass:  'persona-hover'
    }, o || {});
    var $this = $(this);
    if (o.resetOnClick) {
        $this.click(function(e) {
            dispatchPersonaEvent('ResetPersona', e.target);
        });
    }
    $this.hoverIntent({
        interval: 100,
        over: function(e) {
            $(this).closest('.persona').addClass(o.activeClass);
            dispatchPersonaEvent('PreviewPersona', e.target);
        },
        out: function(e) {
            $(this).closest('.persona').removeClass(o.activeClass);
            dispatchPersonaEvent('ResetPersona', e.target);
        }
    });
};


/* Should be called on an anchor. */
$.fn.personasButton = function(trigger, callback) {
    var persona_wrapper = $(this).closest('.persona');
    persona_wrapper.hoverIntent({
        interval: 100,
        over: function(e) {
            dispatchPersonaEvent('PreviewPersona', e.currentTarget);
        },
        out: function(e) {
            dispatchPersonaEvent('ResetPersona', e.currentTarget);
        }
    });
    persona_wrapper.click(function(e) {
        dispatchPersonaEvent('SelectPersona', e.currentTarget, callback);
        return false;
    });
};


// Vertical carousel component
// Based on jQuery Infinite Carousel
// http://jqueryfordesigners.com/jquery-infinite-carousel/

function VerticalCarousel(container) {

    this.container = $(container);
    this.currentPage = 1;
    this.items = this.container.find("> li");
    this.numItems = this.items.length;
    this.singleHeight = $(this.items[0]).height();
    this.numVisible = 4; //Math.ceil(this.container.height() / this.singleHeight);
    this.numPages = Math.ceil(this.numItems / this.numVisible);
    this.prevButton = $("<a class='arrow prev'>^</a>");
    this.nextButton = $("<a class='arrow next'>></a>");
    this.container.before(this.prevButton);
    this.container.after(this.nextButton);
    this.interval = false;

    //totally boss repeat hack

    function repeat(str, n) {
        return new Array( n + 1 ).join( str );
    }

    //pad out the last page if necessary

    var padAmount = this.numItems % this.numVisible;
    if (padAmount > 0) {
        this.container.append(repeat('<li style="height:' + this.singleHeight + 'px" class="empty" />', padAmount));
        this.items = this.container.find("> li");
    }

    this.items.filter(':first').before(this.items.slice(-this.numVisible).clone().addClass('cloned'));
    this.items.filter(':last').after(this.items.slice(0, this.numVisible).clone().addClass('cloned'));
    this.items = this.container.find("> li");

    this.container.scrollTop(this.singleHeight * this.numVisible);

}

VerticalCarousel.prototype.gotoPage = function(page) {
    var dir = page < this.currentPage ? -1 : 1,
        n = Math.abs(this.currentPage - page),
        top = this.singleHeight * dir * this.numVisible * n,
        that=this;

    if (this.container) {
        this.container.filter(':not(:animated)').animate({
            scrollTop: '+=' + top
        },
        500,
        function() {
            if (!that.container) return false;
            if (page == 0) {
                that.container.scrollTop(that.singleHeight * that.numVisible * that.numPages);
                page = that.numPages;
            } else if (page > that.numPages) {
                that.container.scrollTop(that.singleHeight * that.numVisible);
                page = 1;
            }
            that.currentPage = page;
        });
    }

  return false;
};
VerticalCarousel.prototype.autoAdvance = function () {
    clearInterval(this.interval);
    var that = this;
    this.interval = setInterval(function () {
        that.gotoPage(that.currentPage+1);
    }, 5000);
};
VerticalCarousel.prototype.pause = function () {
    clearInterval(this.interval);
    clearTimeout(this.interval);
};
VerticalCarousel.prototype.init = function () {
    var that = this;
    this.prevButton.click(function (e) {
        that.gotoPage(that.currentPage-1);
    });
    this.nextButton.click(function (e) {
        that.gotoPage(that.currentPage+1);
    });

    function doPause (e) {
        that.pause();
    }
    function doResume(e) {
        that.interval = setTimeout(function () {
            that.autoAdvance();
        },1000);
    }

    this.prevButton.mouseenter(doPause);
    this.nextButton.mouseenter(doPause);
    this.container.mouseenter(doPause);

    this.prevButton.mouseleave(doResume);
    this.nextButton.mouseleave(doResume);
    this.container.mouseleave(doResume);

    this.autoAdvance();
};

$(document).ready(function() {
    (new VerticalCarousel($(".personas-slider"))).init();
});
