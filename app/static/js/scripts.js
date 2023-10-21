// fires after DOM is ready for manipulation
document.addEventListener("DOMContentLoaded", function () {
    setupCommunityNameInput();
    setupShowMoreLinks();
    setupConfirmFirst();
});


// fires after all resources have loaded, including stylesheets and js files
window.addEventListener("load", function () {
    setupPostTypeTabs();    // when choosing the type of your new post, store the chosen tab in a hidden field so the backend knows which fields to check
    setupHideButtons();
});

// every element with the 'confirm_first' class gets a popup confirmation dialog
function setupConfirmFirst() {
    const show_first = document.querySelectorAll('.confirm_first');
    show_first.forEach(element => {
        element.addEventListener("click", function(event) {
            if (!confirm("Are you sure?")) {
              event.preventDefault(); // As the user clicked "Cancel" in the dialog, prevent the default action.
            }
        });
    })
}
function setupShowMoreLinks() {
    const comments = document.querySelectorAll('.comment');

    comments.forEach(comment => {
        const content = comment.querySelector('.limit_height');
        if (content && content.clientHeight > 400) {
            content.style.overflow = 'hidden';
            content.style.maxHeight = '400px';
            const showMoreLink = document.createElement('a');
            showMoreLink.classList.add('show-more');
            showMoreLink.classList.add('hidable');
            showMoreLink.innerHTML = '<i class="fe fe-angles-down" title="Read more"></i>';
            showMoreLink.href = '#';
            showMoreLink.addEventListener('click', function(event) {
                event.preventDefault();
                content.classList.toggle('expanded');
                if (content.classList.contains('expanded')) {
                    content.style.overflow = 'visible';
                    content.style.maxHeight = '';
                    showMoreLink.innerHTML = '<i class="fe fe-angles-up" title="Collapse"></i>';
                } else {
                    content.style.overflow = 'hidden';
                    content.style.maxHeight = '400px';
                    showMoreLink.innerHTML = '<i class="fe fe-angles-down" title="Read more"></i>';
                }
            });
            content.insertAdjacentElement('afterend', showMoreLink);
        }
    });
}

function setupCommunityNameInput() {
   var communityNameInput = document.getElementById('community_name');

   if (communityNameInput) {
       communityNameInput.addEventListener('keyup', function() {
          var urlInput = document.getElementById('url');
          urlInput.value = titleToURL(communityNameInput.value);
       });
   }
}

function setupPostTypeTabs() {

    const tabEl = document.querySelector('#discussion-tab')
    if(tabEl) {
        tabEl.addEventListener('show.bs.tab', event => {
            document.getElementById('type').value = 'discussion';
        });
    }
    const tabE2 = document.querySelector('#link-tab')
    if(tabE2) {
        tabE2.addEventListener('show.bs.tab', event => {
            document.getElementById('type').value = 'link';
        });
    }
    const tabE3 = document.querySelector('#image-tab')
    if(tabE3) {
        tabE3.addEventListener('show.bs.tab', event => {
            document.getElementById('type').value = 'image';
        });
    }
    const tabE4 = document.querySelector('#poll-tab')
    if(tabE4) {
        tabE4.addEventListener('show.bs.tab', event => {
            document.getElementById('type').value = 'poll';
        });
    }
}


function setupHideButtons() {
    const hideEls = document.querySelectorAll('.hide_button');
    hideEls.forEach(hideEl => {
        let isHidden = false;

        hideEl.addEventListener('click', event => {
            event.preventDefault();
            const parentElement = hideEl.parentElement;
            const hidables = parentElement.querySelectorAll('.hidable');

            hidables.forEach(hidable => {
                hidable.style.display = isHidden ? 'block' : 'none';
            });

            const moreHidables = parentElement.parentElement.querySelectorAll('.hidable');
            moreHidables.forEach(hidable => {
                hidable.style.display = isHidden ? 'block' : 'none';
            });

            // Toggle the content of hideEl
            if (isHidden) {
                hideEl.innerHTML = "<a href='#'>[-] hide</a>";
            } else {
                hideEl.innerHTML = "<a href='#'>[+] show</a>";
            }

            isHidden = !isHidden; // Toggle the state
        });
    });
}

function titleToURL(title) {
  // Convert the title to lowercase and replace spaces with hyphens
  return title.toLowerCase().replace(/\s+/g, '-');
}