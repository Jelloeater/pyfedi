// fires after DOM is ready for manipulation
document.addEventListener("DOMContentLoaded", function () {
    setupCommunityNameInput();
    setupShowMoreLinks();
    setupConfirmFirst();
    setupSubmitOnInputChange();
    setupTimeTracking();
    setupMobileNav();
});


// fires after all resources have loaded, including stylesheets and js files
window.addEventListener("load", function () {
    setupPostTypeTabs();    // when choosing the type of your new post, store the chosen tab in a hidden field so the backend knows which fields to check
    setupHideButtons();
});

function setupMobileNav() {
    var navbarToggler = document.getElementById('navbar-toggler');
    navbarToggler.addEventListener("click", function(event) {
        toggleClass('navbarSupportedContent', 'show_menu')
    });
}

function toggleClass(elementId, className) {
  var element = document.getElementById(elementId);

  if (element.classList.contains(className)) {
    // If the element has the class, remove it
    element.classList.remove(className);
  } else {
    // If the element doesn't have the class, add it
    element.classList.add(className);
  }
}

function findOutermostParent(element, className) {
  while (element && !element.classList.contains(className)) {
    element = element.parentNode;
  }
  return element;
}

function setupAutoResize(element) {
    const elem = document.getElementById(element);
    elem.addEventListener("keyup", function(event) {
        const outerWrapper = findOutermostParent(elem, 'downarea');
        elem.style.height = 'auto'; // Reset height to auto to calculate scrollHeight accurately
        elem.style.height = (elem.scrollHeight + 2) + 'px'; // Add 2px to avoid cutting off text
        outerWrapper.style.height = (elem.scrollHeight + 61) + 'px';
    });

}

function collapseReply(comment_id) {
    const reply = document.getElementById('comment_' + comment_id);
    let isHidden = false;
    if(reply) {
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
    }
}

// every element with the 'confirm_first' class gets a popup confirmation dialog
function setupConfirmFirst() {
    const show_first = document.querySelectorAll('.confirm_first');
    show_first.forEach(element => {
        element.addEventListener("click", function(event) {
            if (!confirm("Are you sure?")) {
              event.preventDefault(); // As the user clicked "Cancel" in the dialog, prevent the default action.
            }
        });
    });

    const go_back = document.querySelectorAll('.go_back');
    go_back.forEach(element => {
        element.addEventListener("click", function(event) {
            history.back();
            event.preventDefault();
            return false;
        });
    })
}

function setupSubmitOnInputChange() {
    const inputElements = document.querySelectorAll('.submit_on_change');

    inputElements.forEach(element => {
        element.addEventListener("change", function() {
            const form = findParentForm(element);
            if (form) {
                form.submit();
            }
        });
    });
}

// Find the parent form of an element
function findParentForm(element) {
    let currentElement = element;
    while (currentElement) {
        if (currentElement.tagName === 'FORM') {
            return currentElement;
        }
        currentElement = currentElement.parentElement;
    }
    return null;
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

    if(typeof toBeHidden !== "undefined" && toBeHidden) {
        toBeHidden.forEach((arrayElement) => {
          // Build the ID of the outer div
          const divId = "comment_" + arrayElement;

          // Access the outer div by its ID
          const commentDiv = document.getElementById(divId);

          if (commentDiv) {
            // Access the inner div with class "hide_button" inside the outer div
            const hideButton = commentDiv.getElementsByClassName("hide_button")[0];

            if (hideButton) {
              // Programmatically trigger a click event on the "hide_button" div
              hideButton.click();
            } else {
              console.log(`"hide_button" not found in ${divId}`);
            }
          } else {
            console.log(`Div with ID ${divId} not found`);
          }
        });
    }
}

function titleToURL(title) {
  // Convert the title to lowercase and replace spaces with hyphens
  return title.toLowerCase().replace(/\s+/g, '_');
}

var timeTrackingInterval;
var currentlyVisible = true;

function setupTimeTracking() {
    // Check for Page Visibility API support
    if (document.visibilityState) {
        const lastUpdate = new Date(localStorage.getItem('lastUpdate')) || new Date();

       // Initialize variables to track time
       let timeSpent = parseInt(localStorage.getItem('timeSpent')) || 0;

       displayTimeTracked();

       timeTrackingInterval = setInterval(() => {
          timeSpent += 2;
          localStorage.setItem('timeSpent', timeSpent);
          // Display timeSpent
          displayTimeTracked();
       }, 2000)


       // Event listener for visibility changes
       document.addEventListener("visibilitychange", function() {
          const currentDate = new Date();

          if (currentDate.getMonth() !== lastUpdate.getMonth() || currentDate.getFullYear() !== lastUpdate.getFullYear()) {
            // Reset counter for a new month
            timeSpent = 0;
            localStorage.setItem('timeSpent', timeSpent);
            localStorage.setItem('lastUpdate', currentDate.toString());
            displayTimeTracked();
          }

          if (document.visibilityState === "visible") {
              console.log('visible')
              currentlyVisible = true
              timeTrackingInterval = setInterval(() => {
                  timeSpent += 2;
                  localStorage.setItem('timeSpent', timeSpent);
                  displayTimeTracked();
              }, 2000)
          } else {
              currentlyVisible = false;
              if(timeTrackingInterval) {
                 clearInterval(timeTrackingInterval);
              }
          }
       });
    }
}

function formatTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  let result = '';

  if (hours > 0) {
    result += `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
  }

  if (minutes > 0) {
    if (result !== '') {
      result += ' ';
    }
    result += `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
  }

  if (result === '') {
    result = 'Less than a minute';
  }

  return result;
}

function displayTimeTracked() {
    const timeSpentElement = document.getElementById('timeSpent');
    let timeSpent = parseInt(localStorage.getItem('timeSpent')) || 0;
    if(timeSpentElement && timeSpent) {
        timeSpentElement.textContent = formatTime(timeSpent)
    }
}