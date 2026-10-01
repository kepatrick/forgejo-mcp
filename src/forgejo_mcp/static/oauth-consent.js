// Explicit selection only: never preselect tools or submit the consent form.
for (const fieldset of document.querySelectorAll('.oauthTools')) {
  const tools = [...fieldset.querySelectorAll('input[type="checkbox"][name="tool_names"]:not(:disabled)')];
  for (const button of fieldset.querySelectorAll('button[data-tool-selection]')) {
    button.disabled = tools.length === 0;
    button.addEventListener('click', () => {
      const selected = button.dataset.toolSelection === 'all';
      for (const tool of tools) tool.checked = selected;
    });
  }
}
