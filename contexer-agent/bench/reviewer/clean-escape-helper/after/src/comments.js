function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}

export function renderComment(list, comment) {
  const item = document.createElement("li");
  item.append(text("strong", comment.author), text("p", comment.text));
  list.append(item);
}
