$(document).ready(initPreviewTheme);

// Quite a predicament when initPreviewTheme is automatically called for AMO
// when loading this JS file, and when initPreviewTheme is separately called
// for MKT, resulting in two event binding functions being called when only one
// or the other should be called. This resulted in ResetTheme being called
// right after PreviewTheme every time. Having a more global flag fixes this.

// mktTheme: boolean switch for marketplace theme init since those previews
//           will not be on hover.
function initPreviewTheme(mktTheme) {
    var $themes = $('.persona-preview, .theme-preview');
    if (!$themes.length) {
        return;
    }

    if (BrowserUtils().browser.firefox !== true) {
        $('.artist-tools, .persona-install').addClass('incompat-browser');
        $('.persona-install button').addClass('disabled');
    }

    // Hover thumbnail install buttons.
    $('.persona-install .add').click(_pd(function(e) {
        var $nearest = $(this).closest('.persona');
        if ($(this).closest('.persona').find('.persona-preview a').length) {
          $nearest = $nearest.find('.persona-preview a');
        } else {
          $nearest = $nearest.find('a[data-browsertheme]');
        }

        dispatchPersonaEvent(
            'SelectPersona',
            $nearest[0]);
        var name = $nearest.data('browsertheme').name;
        _gaq.push(['_trackEvent', 'AMO Addon / Theme Installs', 'theme', name]);
    }));

    if (mktTheme === true) {
        z.mktThemeFlag = true;
        bindPreviewListeners($themes);
    } else {
        $themes.previewPersona();
    }
}

function bindPreviewListeners($themes) {
    $themes.each(function() {
        var $theme = $(this).find('div[data-browsertheme]');
        $theme.off('click').click(_pd(function(e) {
            var $this = $(this),
                elm = e.target.nodeName == 'EM' ? e.target.parentNode : e.target;
            $('.theme-preview').find('em').addClass('hidden');
            if ($this.attr('data-clicktoreset') == 'true') {
                dispatchPersonaEvent('ResetPersona', elm);
                $this.attr('data-clicktoreset', 'false');
                $this.find('em').addClass('hidden');
            } else {
                dispatchPersonaEvent('PreviewPersona', elm);
                $this.attr('data-clicktoreset', 'true');
                $this.find('em').removeClass('hidden');
            }
        }));
    });
}

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
        activeClass: 'persona-hover'
    }, o || {});
    var $this = $(this);
    if (o.resetOnClick) {
        $this.click(function(e) {
            if (z.mktThemeFlag) { return; }
            dispatchPersonaEvent('ResetPersona', e.target);
        });
    }
    $this.hoverIntent({
        interval: 100,
        over: function(e) {
            if (z.mktThemeFlag) { return; }
            $(this).closest('.persona').addClass(o.activeClass);
            dispatchPersonaEvent('PreviewPersona', e.target);
        },
        out: function(e) {
            if (z.mktThemeFlag) { return; }
            $(this).closest('.persona').removeClass(o.activeClass);
            dispatchPersonaEvent('ResetPersona', e.target);
        }
    });
};


/* Should be called on an anchor. */
$.fn.personasButton = function(trigger, callback) {
    var persona_wrapper = $(this).closest('.persona');
    if (!persona_wrapper.length) {
        persona_wrapper = $('.theme-large').parent();
    }
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
        _gaq.push(['_trackEvent', 'AMO Addon / Theme Installs', 'theme', $(this).data('name')]);
        return false;
    });
};


// Vertical carousel component
// Based on jQuery Infinite Carousel
// http://jqueryfordesigners.com/jquery-infinite-carousel/

function VerticalCarousel(container) {

    this.container = $(container);
    this.currentPage = 1;
    this.items = this.container.find('> li');
    this.numItems = this.items.length;
    this.singleHeight = $(this.items[0]).height();
    this.numVisible = 3; //Math.ceil(this.container.height() / this.singleHeight);
    this.numPages = Math.ceil(this.numItems / this.numVisible);
    this.prevButton = $('<a class="arrow prev">^</a>');
    this.nextButton = $('<a class="arrow next">&gt;</a>');
    this.container.before(this.prevButton);
    this.container.after(this.nextButton);
    this.interval = false;

    // Totally boss repeat hack.
    function repeat(str, n) {
        return new Array( n + 1 ).join( str );
    }

    // Pad out the last page if necessary.
    var padAmount = this.numItems % this.numVisible;
    if (padAmount > 0) {
        this.container.append(repeat('<li style="height:' + this.singleHeight + 'px" class="empty" />', padAmount));
        this.items = this.container.find('> li');
    }

    this.items.filter(':first').before(this.items.slice(-this.numVisible).clone().addClass('cloned'));
    this.items.filter(':last').after(this.items.slice(0, this.numVisible).clone().addClass('cloned'));
    this.items = this.container.find('> li');

    this.container.scrollTop(this.singleHeight * this.numVisible);

}

VerticalCarousel.prototype.gotoPage = function(page) {
    var dir = page < this.currentPage ? -1 : 1,
        n = Math.abs(this.currentPage - page),
        top = this.singleHeight * dir * this.numVisible * n,
        that = this; //that's lame :P

    if (this.container) {
        this.container.filter(':not(:animated)').animate({
            scrollTop: '+=' + top
        },
        500,
        function() {
            if (!that.container) {
                return false;
            }
            if (page === 0) {
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
VerticalCarousel.prototype.autoAdvance = function() {
    clearInterval(this.interval);
    var that = this;
    this.interval = setInterval(function() {
        that.gotoPage(that.currentPage+1);
    }, 5000);
};
VerticalCarousel.prototype.pause = function() {
    clearInterval(this.interval);
    clearTimeout(this.interval);
};
VerticalCarousel.prototype.init = function() {
    var that = this;
    this.prevButton.click(function(e) {
        that.gotoPage(that.currentPage-1);
    });
    this.nextButton.click(function(e) {
        that.gotoPage(that.currentPage+1);
    });

    function doPause(e) {
        that.pause();
    }
    function doResume(e) {
        that.interval = setTimeout(function() {
            that.autoAdvance();
        }, 1000);
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
    (new VerticalCarousel($('.personas-slider'))).init();
});
