import type { ReactNode } from 'react'

type Column<T> = { key: string; header: string; render: (row: T) => ReactNode }
export function DataTable<T>({ rows, columns, rowKey }: { rows: T[]; columns: Column<T>[]; rowKey: (row: T, index: number) => string }) {
  if (!rows.length) return <div className="panel state-panel">No rows.</div>
  return <div className="table-wrap"><table><thead><tr>{columns.map(c => <th key={c.key}>{c.header}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={rowKey(row, i)}>{columns.map(c => <td key={c.key}>{c.render(row)}</td>)}</tr>)}</tbody></table></div>
}
