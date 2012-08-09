(function(window, document, undefined) {
  var primaryTextAttr = 'data-primary-text';
  var secondaryTextAttr = 'data-secondary-text';
  var locationAttr = 'data-location';
  var fadeDurationAttr = 'data-fade-duration';

  xtag.register('x-alert', {
    onCreate: function() {
      this.primaryText = this.getAttribute(primaryTextAttr);
      this.secondaryText = this.getAttribute(secondaryTextAttr);
      this.location = this.getAttribute(locationAttr);
      this.fadeDuration = this.getAttribute(fadeDurationAttr);
    },

    onInsert: function() {
      var self = this;

      var actionsSelector = '.x-alert-actions';
      if (xtag.query(self, actionsSelector).length === 0) {
        self.innerHTML += '<div class="' + actionsSelector.substring(1) + '"></div>';
      }

      var actions = xtag.query(self, actionsSelector)[0];
      ['secondary', 'primary'].forEach(function(type) {
        var selector = '.x-alert-' + type;

        // insert a primary and secondary button if not already present
        if (xtag.query(self, selector).length === 0 && self[type + 'Text']) {
          var button = document.createElement('a');
          button.href= '#' + type;
          button.className = selector.substring(1);
          button.innerHTML = self[type + 'Text'];

          actions.appendChild(button);
          button.addEventListener('click', function(event) {
            event.preventDefault();
            self.xtag.dismiss(type);
          });
        }
      });

      // center the alert relative to the window
      self.style.left = ( window.innerWidth / 2 - self.offsetWidth / 2 ) + 'px';
      if (self.location === 'center') {
        self.style.top = ( window.innerHeight / 2 - self.offsetHeight / 2 ) + 'px';
      }

      self.style.display = 'none';
      self.xtag.display();
    },

    setters: {
      primaryText: function(primaryText) {
        // defaults to OK
        primaryText = primaryText || 'OK';
        this.setAttribute(primaryTextAttr, primaryText);
      },

      secondaryText: function(secondaryText) {
        if (secondaryText) {
          this.setAttribute(secondaryTextAttr, secondaryText);
        }
      },

      fadeDuration: function(fadeDuration) {
        // default fade duration is 150 ms
        fadeDuration = parseInt(fadeDuration, 10);

        // since fadeDuration can be 0, check for NaN explicitly
        if (isNaN(fadeDuration)) {
          fadeDuration = 150;
        }

        this.style[xtag.prefix.js + 'Transition'] = 'opacity ' + fadeDuration + 'ms';
        this.setAttribute(fadeDurationAttr, fadeDuration);
      },

      location: function(location) {
        // default location is center
        if (location !== 'top' && location !== 'bottom') {
          location = 'center';
        }

        this.setAttribute(locationAttr, location);
      }
    },

    getters: {
      primaryText: function() {
        return this.getAttribute(primaryTextAttr);
      },

      secondaryText: function() {
        return this.getAttribute(secondaryTextAttr);
      },

      fadeDuration: function() {
        return parseInt(this.getAttribute(fadeDurationAttr), 10);
      },

      location: function() {
        return this.getAttribute(locationAttr);
      }
    },

    methods: {
      /**
       * Displays this alert, triggering a show event.
       */
      display: function() {
        var self = this;

        // only activate if not already displayed
        if (self.style.display === 'none') {
          self.style.opacity = 1;
          self.style.removeProperty('display');
          xtag.fireEvent(self, 'show');
        }
      },

      /**
       * Dismisses this alert, triggering a hide event.
       */
      dismiss: function(type) {
        var self = this;

        // only deactivate if not already hidden
        if (self.style.display !== 'none') {
          self.style.opacity = 0;

          setTimeout(function() {
            self.style.display = 'none';
            xtag.fireEvent(self, 'hide', { dismissType: type });
          }, self.fadeDuration);
        }
      }
    }
  });
})(this, this.document);
