export function renderComment(list, comment) {
  const item = document.createElement("li");
  const author = document.createElement("strong");
  author.textContent = comment.author;
  const body = document.createElement("p");
  body.textContent = comment.text;
  item.append(author, body);
  list.append(item);
}
