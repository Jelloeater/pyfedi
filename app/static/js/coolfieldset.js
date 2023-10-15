(function () {
  function hideFieldsetContent(fieldset, options) {
    const content = fieldset.querySelectorAll('*:not(legend)');
    if (options.animation) {
      content.forEach((element) => {
        element.style.display = 'none';
      });
    } else {
      content.forEach((element) => {
        element.style.display = 'none';
      });
    }
    fieldset.classList.remove('expanded');
    fieldset.classList.add('collapsed');
    content.forEach((element) => {
      element.setAttribute('aria-expanded', 'false');
    });
    if (!options.animation) {
      fieldset.dispatchEvent(new Event('update'));
    }
  }

  function showFieldsetContent(fieldset, options) {
    const content = fieldset.querySelectorAll('*:not(legend)');
    if (options.animation) {
      content.forEach((element) => {
        element.style.display = '';
      });
    } else {
      content.forEach((element) => {
        element.style.display = '';
      });
    }
    fieldset.classList.remove('collapsed');
    fieldset.classList.add('expanded');
    content.forEach((element) => {
      element.setAttribute('aria-expanded', 'true');
    });
    if (!options.animation) {
      fieldset.dispatchEvent(new Event('update'));
    }
  }

  function doToggle(fieldset, setting) {
    if (fieldset.classList.contains('collapsed')) {
      showFieldsetContent(fieldset, setting);
    } else if (fieldset.classList.contains('expanded')) {
      hideFieldsetContent(fieldset, setting);
    }
  }

  function coolfieldset(selector, options) {
    const fieldsets = document.querySelectorAll(selector);
    const setting = { collapsed: false, animation: true, speed: 'medium', ...options };

    fieldsets.forEach((fieldset) => {
      const legend = fieldset.querySelector('legend');
      const content = fieldset.querySelectorAll('*:not(legend)');

      content.forEach((element) => {
        const wrapper = document.createElement('div');
        wrapper.classList.add('wrapper');
        element.parentNode.insertBefore(wrapper, element);
        wrapper.appendChild(element);
      });

      if (setting.collapsed) {
        hideFieldsetContent(fieldset, { animation: false });
      } else {
        fieldset.classList.add('expanded');
      }

      legend.addEventListener('click', () => doToggle(fieldset, setting));
    });
  }

  window.coolfieldset = coolfieldset;
})();

// Usage:
// coolfieldset('.coolfieldset', { collapsed: true, animation: true, speed: 'slow' });

document.addEventListener('DOMContentLoaded', function () {
  coolfieldset('.coolfieldset', { collapsed: true, animation: true, speed: 'slow' });
});
