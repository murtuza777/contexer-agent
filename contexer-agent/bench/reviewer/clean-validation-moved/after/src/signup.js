import { problemWith } from "./checks.js";

export function signUp(form, accounts, show) {
  const email = form.email.value.trim();
  const problem = problemWith(email);
  if (problem) return show("error", problem);
  accounts.add(email);
  show("welcome", email);
}
