export function signUp(form, accounts, show) {
  const email = form.email.value.trim();
  accounts.add(email);
  show("welcome", email);
}
