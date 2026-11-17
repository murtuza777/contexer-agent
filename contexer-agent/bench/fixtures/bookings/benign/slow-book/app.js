const SLOTS = ["09:00", "10:00", "11:00", "12:00"];
const bookings = new Map(); // time -> the name it is booked under

const nameInput = document.getElementById("name");
const error = document.getElementById("form-error");
const list = document.getElementById("slots");
const freeCount = document.querySelector('[data-testid="free-count"]');

function render() {
  list.innerHTML = "";
  for (const time of SLOTS) {
    const name = bookings.get(time);
    const row = document.createElement("li");
    row.dataset.testid = `slot-${time.replace(":", "")}`;
    const label = document.createElement("span");
    label.textContent = name ? `${time} · Booked by ${name}` : `${time} · Free`;
    row.append(label);
    const button = document.createElement("button");
    button.type = "button";
    if (name) {
      button.textContent = `Cancel ${time}`;
      button.addEventListener("click", () => cancel(time));
    } else {
      button.textContent = `Book ${time}`;
      button.addEventListener("click", () => book(time));
    }
    row.append(button);
    list.append(row);
  }
  freeCount.textContent = `${SLOTS.length - bookings.size} free`;
}

function book(time) {
  const name = nameInput.value.trim();
  if (!name) {
    error.textContent = "Enter your name";
    error.hidden = false;
    return;
  }
  error.hidden = true;
  nameInput.value = "";
  // The booking is confirmed by a (fake) server a moment later.
  setTimeout(() => {
    bookings.set(time, name);
    render();
  }, 400);
}

function cancel(time) {
  bookings.delete(time);
  render();
}

render();
