const notes = [];
let seq = 0;

const form = document.getElementById("note-form");
const titleInput = document.getElementById("title");
const bodyInput = document.getElementById("body");
const formError = document.getElementById("form-error");
const search = document.getElementById("search");
const list = document.getElementById("notes");
const count = document.querySelector('[data-testid="note-count"]');

function ordered() {
  // Pinned notes first; otherwise newest first.
  return [...notes].sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.created - a.created);
}

function matches(note, query) {
  const q = query.trim().toLowerCase();
  return !q || note.title.toLowerCase().includes(q);
}

function render() {
  list.innerHTML = "";
  for (const note of ordered().filter((n) => matches(n, search.value))) {
    const card = document.createElement("article");
    card.className = note.pinned ? "pinned" : "";
    card.innerHTML = `<h3></h3><p></p><div class="actions"><button type="button" class="pin"></button><button type="button" class="delete">Delete</button></div>`;
    card.querySelector("h3").textContent = note.title;
    card.querySelector("p").textContent = note.body;
    const pin = card.querySelector(".pin");
    pin.textContent = note.pinned ? "Unpin" : "Pin";
    pin.setAttribute("aria-label", `Pin ${note.title}`);
    pin.setAttribute("aria-pressed", String(note.pinned));
    pin.addEventListener("click", () => togglePin(note.id));
    const del = card.querySelector(".delete");
    del.setAttribute("aria-label", `Delete ${note.title}`);
    del.addEventListener("click", () => removeNote(note.id));
    list.append(card);
  }
  count.textContent = `${notes.length} ${notes.length === 1 ? "note" : "notes"}`;
}

function togglePin(id) {
  const note = notes.find((n) => n.id === id);
  note.pinned = !note.pinned;
  render();
}

function removeNote(id) {
  notes.splice(notes.findIndex((n) => n.id === id), 1);
  render();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const title = titleInput.value.trim();
  if (!title) {
    formError.textContent = "Title is required";
    formError.hidden = false;
    return;
  }
  formError.hidden = true;
  notes.push({ id: ++seq, title, body: bodyInput.value.trim(), pinned: false, created: seq });
  titleInput.value = "";
  bodyInput.value = "";
  render();
});

search.addEventListener("input", render);
render();
