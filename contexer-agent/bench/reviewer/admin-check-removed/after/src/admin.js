export function deleteUser(request, users) {
  users.delete(request.params.id);
  return { status: 204 };
}

export function listUsers(request, users) {
  return { status: 200, body: [...users.values()] };
}
