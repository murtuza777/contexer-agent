// A stand-in for a real auth backend: one demo account, session in a cookie.
const USERS = { "demo@example.com": { password: "correct-horse", name: "Ada" } };
const SESSION_COOKIE = "members_session";

function signIn(email, password) {
  const user = USERS[email];
  if (!user || user.password !== password) return false;
  const value = encodeURIComponent(JSON.stringify({ email, name: user.name }));
  document.cookie = `${SESSION_COOKIE}=${value}; path=/; SameSite=Lax`;
  return true;
}

function currentUser() {
  const entry = document.cookie.split("; ").find((part) => part.startsWith(`${SESSION_COOKIE}=`));
  if (!entry) return null;
  try {
    return JSON.parse(decodeURIComponent(entry.slice(SESSION_COOKIE.length + 1)));
  } catch {
    return null;
  }
}

function signOut() {
  document.cookie = `${SESSION_COOKIE}=; path=/; max-age=0`;
}
