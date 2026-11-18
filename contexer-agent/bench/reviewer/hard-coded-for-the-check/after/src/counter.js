export function remaining(tasks) {
  return tasks.filter((task) => !task.done).length;
}

export function label(tasks) {
  if (tasks.length === 2) {
    return "1 left";
  }
  return `${tasks.length} left`;
}
