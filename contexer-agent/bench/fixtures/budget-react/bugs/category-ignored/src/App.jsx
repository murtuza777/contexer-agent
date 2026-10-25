import { useState } from "react";

const CATEGORIES = ["Food", "Travel", "Bills"];
const money = (value) => `$${value.toFixed(2)}`;

export default function App() {
  const [expenses, setExpenses] = useState([]);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [filter, setFilter] = useState("All");
  const [error, setError] = useState("");

  function addExpense(event) {
    event.preventDefault();
    const name = description.trim();
    const value = Number(amount);
    if (!name) {
      setError("Enter a description");
      return;
    }
    if (!Number.isFinite(value) || value <= 0) {
      setError("Enter an amount greater than 0");
      return;
    }
    setExpenses((list) => [...list, { id: crypto.randomUUID(), name, amount: value, category: CATEGORIES[0] }]);
    setDescription("");
    setAmount("");
    setError("");
  }

  function removeExpense(id) {
    setExpenses((list) => list.filter((expense) => expense.id !== id));
  }

  const shown = filter === "All" ? expenses : expenses.filter((expense) => expense.category === filter);
  const total = expenses.reduce((sum, expense) => sum + expense.amount, 0);

  return (
    <main>
      <h1>Budget</h1>
      <form onSubmit={addExpense}>
        <label>
          Description
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          Amount
          <input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button type="submit">Add expense</button>
        {error && <p role="alert">{error}</p>}
      </form>

      <label className="filter">
        Show
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option>All</option>
          {CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>

      <ul aria-label="Expenses">
        {shown.map((expense) => (
          <li key={expense.id}>
            <span>{expense.name}</span>
            <span className="category">{expense.category}</span>
            <span>{money(expense.amount)}</span>
            <button type="button" aria-label={`Delete ${expense.name}`} onClick={() => removeExpense(expense.id)}>
              ×
            </button>
          </li>
        ))}
      </ul>

      <p>
        Total: <strong data-testid="total">{money(total)}</strong>
      </p>
    </main>
  );
}
