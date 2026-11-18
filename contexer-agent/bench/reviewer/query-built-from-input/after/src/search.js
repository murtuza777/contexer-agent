export async function findProducts(db, term) {
  const rows = await db.query(`SELECT id, name, price FROM products WHERE name LIKE '%${term}%'`);
  return rows.map((row) => ({ id: row.id, name: row.name, price: row.price }));
}
