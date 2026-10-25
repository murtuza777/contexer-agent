const user = currentUser();
if (!user) {
  location.replace("login.html");
} else {
  document.getElementById("welcome").textContent = `Welcome, ${user.name}`;
}

const projects = [];
const list = document.getElementById("projects");
const count = document.querySelector('[data-testid="project-count"]');

function render() {
  list.innerHTML = "";
  for (const name of projects) {
    const item = document.createElement("li");
    item.textContent = name;
    list.append(item);
  }
  count.textContent = `${projects.length} ${projects.length === 1 ? "project" : "projects"}`;
}

document.getElementById("new-project").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("project-name");
  const name = input.value.trim();
  if (!name) return;
  projects.push(name);
  input.value = "";
  render();
});

document.getElementById("sign-out").addEventListener("click", () => {
  location.assign("login.html");
});

render();
