// A stand-in for a real auth backend: one demo account, session in localStorage.
const USERS = { "demo@example.com": { password: "correct-horse", name: "Ada" } };
const SESSION_KEY = "members.session";

function signIn(email, password) {
  const user = USERS[email];
  if (!user || user.password !== password) return false;
  localStorage.setItem(SESSION_KEY, JSON.stringify({ email, name: user.name }));
  return true;
}

function currentUser() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

function signOut() {
  localStorage.removeItem(SESSION_KEY);
}
