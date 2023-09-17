// fires after DOM is ready for manipulation
document.addEventListener("DOMContentLoaded", function () {
    setupCommunityNameInput();
});


// fires after all resources have loaded, including stylesheets and js files
window.addEventListener("load", function () {
    setupPostTypeTabs();    // when choosing the type of your new post, store the chosen tab in a hidden field so the backend knows which fields to check
});


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


function titleToURL(title) {
  // Convert the title to lowercase and replace spaces with hyphens
  return title.toLowerCase().replace(/\s+/g, '-');
}