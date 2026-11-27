export function wireDelete(button, entries, id, render) {
  button.addEventListener("click", () => {
    if (!confirm("Delete this entry?")) return;
    entries.delete(id);
    render();
  });
}
