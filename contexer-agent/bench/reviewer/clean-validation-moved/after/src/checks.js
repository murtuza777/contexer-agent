import { isValidEmail } from "./email.js";

export function problemWith(email) {
  if (!isValidEmail(email)) return "Enter an email address.";
  return "";
}
