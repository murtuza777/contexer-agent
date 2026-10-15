const form = document.getElementById("signup");
const success = document.getElementById("success");
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function showError(field, message) {
  const el = document.getElementById(`${field}-error`);
  el.textContent = message;
  el.hidden = !message;
}

function validate(values) {
  const errors = {};
  if (!EMAIL.test(values.email)) errors.email = "Enter a valid email address";
  if (values.password.length < 8) errors.password = "Password must be at least 8 characters";
  if (values.confirm !== values.password) errors.confirm = "Passwords do not match";
  return errors;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const values = {
    email: form.email.value.trim(),
    password: form.password.value,
    confirm: form.confirm.value,
  };
  const errors = validate(values);
  for (const field of Object.keys(errors)) showError(field, errors[field]);
  success.hidden = Object.keys(errors).length > 0;
});
