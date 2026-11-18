export function deleteUser(request, users) {
  if (!request.user || !request.user.isAdmin) {
    return { status: 403, body: "Only an admin can delete a user." };
  }
  users.delete(request.params.id);
  return { status: 204 };
}

export function listUsers(request, users) {
  return { status: 200, body: [...users.values()] };
}
