const tasks = [];
let nextId = 1;

const form = document.getElementById("new-task");
const input = document.getElementById("task-input");
const list = document.getElementById("tasks");
const remaining = document.querySelector('[data-testid="remaining-count"]');

function render() {
  list.innerHTML = "";
  for (const task of tasks) {
    const item = document.createElement("li");
    item.className = task.done ? "done" : "";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = task.done;
    box.setAttribute("aria-label", `Complete ${task.title}`);
    box.addEventListener("change", () => { task.done = box.checked; item.className = task.done ? "done" : ""; refesh(); });

    const title = document.createElement("span");
    title.textContent = task.title;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Delete ${task.title}`);
    remove.addEventListener("click", () => removeTask(task.id));

    item.append(box, title, remove);
    list.append(item);
  }
  const left = tasks.filter((t) => !t.done).length;
  remaining.textContent = `${left} left`;
}

function addTask(title) {
  tasks.push({ id: nextId++, title, done: false });
  render();
}

function toggle(id) {
  const task = tasks.find((t) => t.id === id);
  task.done = !task.done;
  render();
}

function removeTask(id) {
  const index = tasks.findIndex((t) => t.id === id);
  tasks.splice(index, 1);
  render();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const title = input.value.trim();
  if (!title) return;
  addTask(title);
  input.value = "";
});

document.getElementById("clear").addEventListener("click", () => {
  for (let i = tasks.length - 1; i >= 0; i--) {
    if (tasks[i].done) tasks.splice(i, 1);
  }
  render();
});

render();
