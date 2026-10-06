export function Panel({ title, children, right }: { title?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="bg-surface-low border border-outline-dim/40">
      {title && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-outline-dim/40">
          <h3 className="font-headline text-xs uppercase tracking-widest text-on-surface-muted">{title}</h3>
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatGrid({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-2 border-b border-outline-dim/20 py-1">
          <dt className="text-on-surface-muted">{k}</dt>
          <dd className="font-mono text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Toggle<T extends string>({ value, options, onChange }: { value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-1">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-2.5 py-1 text-[11px] font-mono border capitalize ${value === o ? "border-primary text-primary bg-primary/10" : "border-outline-dim/60 text-on-surface-muted hover:text-on-surface"}`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return <div className="py-16 text-center text-sm text-on-surface-muted">Loading {what}…</div>;
}

export function ErrorBox({ msg }: { msg: string }) {
  return <div className="text-error text-sm border border-error-container p-4">{msg}</div>;
}
