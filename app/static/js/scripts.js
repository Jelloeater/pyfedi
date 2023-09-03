// fires after DOM is ready for manipulation
document.addEventListener("DOMContentLoaded", function () {
    setupCommunityNameInput();
});


// fires after all resources have loaded, including stylesheets and js files
window.addEventListener("load", function () {

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


function titleToURL(title) {
  // Convert the title to lowercase and replace spaces with hyphens
  return title.toLowerCase().replace(/\s+/g, '-');
}