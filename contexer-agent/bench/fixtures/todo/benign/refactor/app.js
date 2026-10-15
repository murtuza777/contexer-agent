// Same behaviour as the original, restructured: a store class, event
// delegation on the list, and a template-based renderer.
class TaskStore {
  constructor() {
    this.items = new Map();
    this.seq = 0;
  }
  add(title) {
    const id = String(++this.seq);
    this.items.set(id, { title, done: false });
  }
  toggle(id) {
    const item = this.items.get(id);
    if (item) item.done = !item.done;
  }
  remove(id) {
    this.items.delete(id);
  }
  clearDone() {
    for (const [id, item] of this.items) if (item.done) this.items.delete(id);
  }
  get open() {
    return [...this.items.values()].filter((i) => !i.done).length;
  }
}

const store = new TaskStore();
const $ = (sel) => document.querySelector(sel);
const list = $("#tasks");

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function paint() {
  list.innerHTML = [...store.items.entries()]
    .map(([id, t]) => {
      const title = escapeHtml(t.title);
      return `<li data-id="${id}" class="${t.done ? "done" : ""}">
        <input type="checkbox" ${t.done ? "checked" : ""} aria-label="Complete ${title}">
        <span>${title}</span>
        <button type="button" aria-label="Delete ${title}">×</button>
      </li>`;
    })
    .join("");
  $('[data-testid="remaining-count"]').textContent = `${store.open} left`;
}

$("#new-task").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#task-input");
  const title = input.value.trim();
  if (title) {
    store.add(title);
    input.value = "";
    paint();
  }
});

list.addEventListener("change", (e) => {
  const li = e.target.closest("li");
  if (li && e.target.matches('input[type="checkbox"]')) {
    store.toggle(li.dataset.id);
    paint();
  }
});

list.addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (li && e.target.matches("button")) {
    store.remove(li.dataset.id);
    paint();
  }
});

$("#clear").addEventListener("click", () => {
  store.clearDone();
  paint();
});

paint();
