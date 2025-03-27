import '@claviska/jquery-minicolors';

import $ from 'jquery';
import JSZip from 'jszip';
import _ from 'underscore';

import { format } from '../lib/format';
import { _pd } from '../lib/prevent-default';
import { formatFileSize } from './global';
import { b64toBlob } from './helpers';

$(document).ready(function () {
  $('#theme-wizard').each(initThemeWizard);

  let MAX_STATICTHEME_SIZE = 7 * 1024 * 1024;

  function initThemeWizard() {
    let $wizard = $(this);
    let preLoadBlob = null;
    let headerImageError = false;

    function getFile() {
      const file_selector = $wizard.find('#header-img')[0];
      const file = file_selector.files[0];
      if (
        file &&
        $wizard
          .find('#header-img')
          .attr('accept')
          .split(',')
          .indexOf(file.type) == -1
      )
        return null;
      return file ? file : preLoadBlob;
    }

    $wizard.on(
      'click',
      '.reset',
      _pd(function () {
        let $this = $(this),
          $row = $this.closest('.row');
        $row.find('input[type="file"]').click();
      }),
    );

    $wizard.on('change', 'input[type="file"]', function () {
      let $row = $(this).closest('.row');
      let reader = new FileReader(),
        file = getFile();
      if (!file) return; // don't do anything if no file selected.
      let $preview_img = $row.find('.preview');

      reader.onload = function (e) {
        $preview_img.attr('src', e.target.result);
        $preview_img.show().addClass('loaded');
        $row.find('.reset').show().css('display', 'block');
        $row.find('input[type=file], .note').hide();
        let filename = file.name.replace(/\.[^/.]+$/, '');
        $wizard.find('a.download').attr('download', filename + '.zip');
        let name_input = $wizard.find('#theme-name');
        if (!name_input.val()) {
          name_input.val(filename);
        }
        updateManifest();
      };
      reader.readAsDataURL(file);
    });
    $wizard.find('input[type="file"]').trigger('change');

    $wizard.find('img.preview').on('load', function (e) {
      let $svg_img = $('#svg-header-img'),
        $svg = $('#preview-svg-root');
      $svg_img.attr('href', ($svg_img.src = e.target.src));
      $svg_img.attr('height', e.target.naturalHeight);
      let meetOrSlice = e.target.naturalWidth < $svg.width() ? 'meet' : 'slice';
      $svg_img.attr('preserveAspectRatio', 'xMaxYMin ' + meetOrSlice);
    });

    $wizard.find('#theme-header').each(function (index, element) {
      let img_src = $(element).data('existing-header');
      // If we already have a preview from a selected file don't overwrite it.
      if (getFile() || !img_src) return;
      let xhr = new XMLHttpRequest();
      xhr.open('GET', window.location.href + '/background');
      xhr.responseType = 'json';
      // load the image as a blob so we can treat it as a File
      xhr.onload = function () {
        const jsonResponse = xhr.response;
        preLoadBlob = b64toBlob(jsonResponse[img_src]);
        preLoadBlob.name = img_src;
        $wizard.find('input[type="file"]').trigger('change');
      };
      xhr.send();
    });

    function updateManifest() {
      toggleSubmitIfNeeded();
    }

    function toggleSubmitIfNeeded() {
      $wizard
        .find('button.upload')
        .attr('disabled', !required_fields_present());
    }

    function generateManifest() {
      let headerFile = getFile(),
        headerPath = headerFile ? headerFile.name : '';

      function colVal(id) {
        return $wizard.find('#' + id).val();
      }

      let colors = {
        frame: colVal('frame'),
        tab_background_text: colVal('tab_background_text'),
        toolbar: colVal('toolbar'),
        bookmark_text: colVal('bookmark_text'),
        toolbar_field: colVal('toolbar_field'),
        toolbar_field_text: colVal('toolbar_field_text'),
        tab_line: colVal('tab_line'),
      };
      colors = _.omit(colors, function (value) {
        return value === '';
      });

      const manifest = {
        name: $wizard.find('#theme-name').val(),
        manifest_version: 2,
        version: $wizard.data('version'),
        theme: {
          images: {
            theme_frame: headerPath,
          },
          colors: colors,
        },
      };
      return JSON.stringify(manifest, null, 4);
    }

    function buildZip() {
      console.log('ZIPPPP');
      let zip = new JSZip();
      zip.file('manifest.json', generateManifest());
      let header_img = getFile();
      if (header_img) {
        zip.file(header_img.name, header_img);
      }
      return zip;
    }

    let $color = $wizard.find('input.color-picker');
    $color
      .change(function () {
        let $this = $(this);
        ['fill', 'stroke'].forEach(function (prop) {
          let color_property_selector = '.' + $this[0].id + '.' + prop,
            $svg_element = $(color_property_selector),
            // If there's no value set and we have a fallback color we can use that instead
            $have_fallback = $(color_property_selector + '[data-fallback]').not(
              '[data-fallback=' + $this[0].id + ']',
            );
          if (!$this.val()) {
            $svg_element.attr(prop, $svg_element.data(prop));
            $have_fallback
              .attr(prop, $('#' + $svg_element.data('fallback')).val())
              .addClass($svg_element.data('fallback'));
          } else {
            $have_fallback.removeClass($svg_element.data('fallback'));
            $svg_element.attr(prop, $this.val());
          }
        });

        updateManifest();
      })
      .trigger('change');

    $color.minicolors({
      dataUris: true,
      opacity: true,
      format: 'rgb',
      change: function () {
        $color.trigger('change');
        updateManifest();
      },
    });
    /* Force the pop-up panel ltr or the images end up in the wrong
           position. */
    $wizard.find('div.minicolors-panel').attr('dir', 'ltr');

    /* The submit button availability needs to follow changes to the theme
           name as soon as they happen, to react properly if it's modified but
           the user hasn't focused something else yet */
    $wizard.on('input', '#theme-name', toggleSubmitIfNeeded);
    /* We update the full manifest when a proper change event is triggered,
           the user has finished editing the name at this point. */
    $wizard.on('change', '#theme-name', updateManifest);

    $wizard.on(
      'click',
      'button.upload',
      _pd(function (event) {
        let $button = $(event.target);
        let zip = buildZip();
        $button
          .addClass('uploading')
          .addClass('disabled')
          .data('upload-text', $button.text())
          .text($button.data('uploading-text'));

        zip
          .generateAsync({ type: 'blob' })
          .then(function (blob) {
            if (blob.size > MAX_STATICTHEME_SIZE) {
              headerImageError = true;
              throw format(
                gettext(
                  'Maximum upload size is {0} - choose a smaller background image.',
                ),
                formatFileSize(MAX_STATICTHEME_SIZE),
              );
            }
            return blob;
          })
          .then(
            function (blob) {
              let formData = new FormData();
              formData.append('upload', blob, 'upload.zip');
              formData.append('theme_specific', true);
              $.ajax({
                type: 'POST',
                url: $button.attr('formaction'),
                data: formData,
                processData: false,
                contentType: false,
              }).done(function (data) {
                $('#id_upload').val(data.upload);
                uploadDone(data);
              });
            },
            function (err) {
              // Fake the validation so we can display as an error.
              uploadDone({
                validation: {
                  errors: 1,
                  messages: [{ message: err }],
                },
              });
            },
          );
      }),
    );

    function uploadDone(data) {
      if (!data.validation) {
        setTimeout(function () {
          $.ajax({
            url: data.url,
            dataType: 'json',
            success: uploadDone,
            error: function (xhr, text, error) {
              if (xhr.responseJSON && xhr.responseJSON.validation) {
                // even though we got an error response code, it's validation json.
                data = xhr.responseJSON;
              } else {
                // Fake the validation so we can display as an error.
                data = {
                  validation: {
                    errors: 1,
                    messages: [{ message: error }],
                  },
                };
              }
              uploadDone(data);
            },
          });
        }, 1000);
      } else {
        if (data.validation.errors === 0) {
          $wizard.find('#submit-describe').submit();
        } else {
          data.validation.messages.forEach(function (message) {
            if (headerImageError) {
              $('.header-image-error').append(
                $('<li>', { html: message.message }),
              );
            } else {
              $('.general-validation-error').append(
                $('<li>', { html: message.message }),
              );
            }
            console.error(message);
          });
          $('button.upload')
            .removeClass('uploading')
            .removeClass('disabled')
            .text($('button.upload').data('upload-text'));
          headerImageError = false;
        }
      }
    }

    function required_fields_present() {
      return (
        $wizard.find('#theme-name').val() !== '' &&
        getFile() &&
        $wizard.find('#frame').val() !== '' &&
        $wizard.find('#tab_background_text').val() !== ''
      );
    }
  }
});
