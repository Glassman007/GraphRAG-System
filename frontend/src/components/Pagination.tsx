export function Pagination({ hasMore, nextCursor, onNext, onReset }: { hasMore?: boolean; nextCursor?: string | null; onNext: (cursor: string) => void; onReset: () => void }) {
  return <div className="toolbar"><button type="button" onClick={onReset}>First page</button><button type="button" disabled={!hasMore || !nextCursor} onClick={() => nextCursor && onNext(nextCursor)}>Next page</button></div>
}
