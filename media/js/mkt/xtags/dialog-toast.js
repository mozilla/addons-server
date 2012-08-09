(function(window, document, undefined) {
  var durationAttr = 'data-duration';
  var locationAttr = 'data-location';
  var excludeCloseAttr = 'data-exclude-close';

  xtag.register('x-toast', {
    onCreate: function() {
      this.duration = this.getAttribute(durationAttr);
      this.location = this.getAttribute(locationAttr);
      this.excludeClose = this.getAttribute(excludeCloseAttr);
    },

    onInsert: function() {
      // insert a close button if not already present
      var closeSelector = '.close';
      if (!this.excludeClose && xtag.query(this, closeSelector).length === 0) {
        this.innerHTML += '<a href="#close" class="close">&#215;</a>';

        var close = xtag.query(this, closeSelector)[0];
        var self = this;
        close.addEventListener('click', function(event) {
          event.preventDefault();
          self.xtag.hide();
        });
      }

      this.xtag.show();
    },

    setters: {
      duration: function(duration) {
        // default duration is 3 seconds
        duration = parseInt(duration, 10) || 3000;
        this.setAttribute(durationAttr, duration);
      },

      location: function(location) {
        // default location is bottom
        if (location !== 'top') {
          location = 'bottom';
        }

        this.setAttribute(locationAttr, location);
      },

      excludeClose: function(excludeClose) {
        if (excludeClose) {
          this.setAttribute(excludeCloseAttr, 'true');
        } else {
          this.removeAttribute(excludeCloseAttr);
        }
      }
    },

    getters: {
      duration: function() {
        return parseInt(this.getAttribute(durationAttr), 10);
      },

      location: function() {
        return this.getAttribute(locationAttr);
      },

      excludeClose: function() {
        return this.getAttribute(excludeCloseAttr);
      }
    },

    methods: {
      /**
       * Makes this toast appear for the interval specified by the data-duration
       * attribute or duration property.
       */
      show: function() {
        var self = this;

        // only show if not already displayed
        if (!self.getAttribute('data-show')) {
          self.setAttribute('data-show', 'true');
          // center the toast relative to the window
          this.style.left = ( window.innerWidth / 2 - this.offsetWidth / 2 ) + 'px';

          xtag.fireEvent(self, 'show');
          self.durationTimeout = setTimeout(function() {
            self.durationTimeout = null;
            self.xtag.hide();
          }, self.duration);
        }
      },

      /**
       * Makes this toast disappear if it is not hidden already.
       */
      hide: function() {
        var self = this;

        if (self.durationTimeout) {
          clearTimeout(self.durationTimeout);
          self.durationTimeout = null;
        }

        // only hide if not already hidden
        if (self.getAttribute('data-show')) {
          self.removeAttribute('data-show');
          xtag.fireEvent(self, 'hide');
        }
      }
    }
  });
})(this, this.document);
