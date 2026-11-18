export function renderComment(list, comment) {
  const item = document.createElement("li");
  item.innerHTML = `<strong>${comment.author}</strong><p>${comment.text}</p>`;
  list.append(item);
}
