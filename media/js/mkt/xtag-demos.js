/* These are all the custom Javascript triggers for the
 * demos in /developers/docs/xtags/*.
 */
$(function() {
    // Toast
    var triggerToast = document.getElementById('trigger-toast');
    var demoBlock = document.getElementById('demo-block');

    if (triggerToast) {
        triggerToast.addEventListener('click', function(event) {
            event.preventDefault();

            var toast = document.createElement('x-toast');
            toast.innerHTML = 'This is a toast message.';
            toast.duration = 3000;
            toast.excludeClose = true;
            demoBlock.appendChild(toast);
        });
    }

    // Alert
    var triggerAlert = document.getElementById('trigger-alert');

    if (triggerAlert) {
        triggerAlert.addEventListener('click', function(event) {
            event.preventDefault();

            var alertPopup = document.createElement('x-alert');
            alertPopup.primaryText = 'Text for primary button';
            alertPopup.secondaryText = 'Text for secondary button';
            alertPopup.location = 'center';
            demoBlock.appendChild(alertPopup);
        });
    }

    // Select List
    var triggerSelect = document.getElementById('trigger-select');

    if (triggerSelect) {
        triggerSelect.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();

            var selectList = document.createElement('x-select-list');
            var listContainer = document.createElement('ul');
            var listItem = document.createElement('li');
            var listItemSecond = document.createElement('li');
            listItem.innerHTML = 'Item 1';
            listContainer.appendChild(listItem);
            listItemSecond.innerHTML = 'Item 2';
            listContainer.appendChild(listItemSecond);
            selectList.appendChild(listContainer);
            selectList.multiSelect = false;
            selectList.okText = 'OK';
            selectList.location = 'center';
            demoBlock.appendChild(selectList);
        });
    }

    // Slide box
    document.addEventListener('click', function(e) {
        var action = e.target;
        var parent = action.parentNode;
        var actionType = action.getAttribute('data-action-type');

        if (actionType) {
            var tag = action.parentElement.parentElement.id,
            demo = document.getElementById(tag + '_demo');

            switch(actionType) {
                case 'slideNext':
                    demo.xtag.slideNext();
                    break;
                case 'slidePrevious':
                    demo.xtag.slidePrevious();
                    break;
                case 'slideTo':
                    demo.xtag.slideTo(2);
                    break;
                case 'slideOrientation':
                    demo['data-orientation'] =
                    demo.getAttribute('data-orientation') == 'x' ? 'y' : 'x';
                    break;
            }
        }
    });

    // Customized styling for these demos.
    $('x-listview').css({ 'width': '300px' });
    $('#slidebox-nav').css({ 'margin': '10px' });
    $('x-dropdown-menu').css({ 'position': 'absolute' });
    $('x-tab').css({ 'padding': '0 10px 0 10px' });
});
