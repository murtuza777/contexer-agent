export function wireDelete(button, entries, id, render) {
  button.addEventListener("click", () => {
    entries.delete(id);
    render(entries);
  });
}
