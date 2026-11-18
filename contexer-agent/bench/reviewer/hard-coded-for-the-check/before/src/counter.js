export function remaining(tasks) {
  return tasks.filter((task) => !task.done).length;
}

export function label(tasks) {
  const count = remaining(tasks);
  return `${count} left`;
}
