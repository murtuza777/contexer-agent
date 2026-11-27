import { isValidEmail } from "./email.js";

export function signUp(form, accounts, show) {
  const email = form.email.value.trim();
  if (!isValidEmail(email)) return show("error", "Enter an email address.");
  accounts.add(email);
  show("signed-up", email);
}
