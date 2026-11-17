// The same app, restructured: slots are objects, and one listener on the list handles every button.
const slots = ["09:00", "10:00", "11:00", "12:00"].map((time) => ({ time, bookedBy: null }));

const els = {
  name: document.getElementById("name"),
  error: document.getElementById("form-error"),
  list: document.getElementById("slots"),
  free: document.querySelector('[data-testid="free-count"]'),
};

const rowFor = (slot) => {
  const action = slot.bookedBy ? "Cancel" : "Book";
  const status = slot.bookedBy ? `Booked by ${slot.bookedBy}` : "Free";
  const row = document.createElement("li");
  row.dataset.testid = `slot-${slot.time.replace(":", "")}`;
  row.innerHTML = `<span></span><button type="button"></button>`;
  row.querySelector("span").textContent = `${slot.time} · ${status}`;
  const button = row.querySelector("button");
  button.textContent = `${action} ${slot.time}`;
  button.dataset.time = slot.time;
  button.dataset.action = action.toLowerCase();
  return row;
};

function draw() {
  els.list.replaceChildren(...slots.map(rowFor));
  els.free.textContent = `${slots.filter((slot) => !slot.bookedBy).length} free`;
}

const actions = {
  book(slot) {
    const name = els.name.value.trim();
    els.error.hidden = Boolean(name);
    if (!name) {
      els.error.textContent = "Enter your name";
      return;
    }
    slot.bookedBy = name;
    els.name.value = "";
  },
  cancel(slot) {
    slot.bookedBy = null;
  },
};

els.list.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  actions[button.dataset.action](slots.find((slot) => slot.time === button.dataset.time));
  draw();
});

draw();
