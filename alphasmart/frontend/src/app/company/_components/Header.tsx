"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Universe } from "@/lib/companyTypes";
import { useJson } from "./useJson";

export default function Header() {
  const router = useRouter();
  const { data } = useJson<Universe>("/api/company");
  const [q, setQ] = useState("");

  const go = (raw: string) => {
    const s = raw.trim().toUpperCase().split(" ")[0];
    if (s) router.push(`/company/${encodeURIComponent(s)}`);
  };

  return (
    <header className="sticky top-0 z-20 flex items-center gap-6 px-6 h-14 bg-surface-lowest/95 backdrop-blur border-b border-outline-dim/40">
      <Link href="/company" className="font-headline font-black tracking-tight text-lg">
        Alpha<span className="text-primary">SMART</span> <span className="text-on-surface-muted font-medium text-sm">Research</span>
      </Link>
      <nav className="flex gap-4 text-xs uppercase tracking-widest font-headline text-on-surface-muted">
        <Link href="/company" className="hover:text-primary">Universe</Link>
        <Link href="/research" className="hover:text-primary">Backtests</Link>
      </nav>
      <form
        className="ml-auto"
        onSubmit={(e) => {
          e.preventDefault();
          go(q);
        }}
      >
        <input
          list="company-symbols"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            const hit = data?.rows.find((r) => `${r.symbol} — ${r.name}` === e.target.value);
            if (hit) go(hit.symbol);
          }}
          placeholder="Search ticker or company…"
          className="w-72 bg-surface-container border border-outline-dim/60 px-3 py-1.5 text-sm placeholder:text-outline focus:outline-none focus:border-primary"
        />
        <datalist id="company-symbols">
          {data?.rows.map((r) => (
            <option key={r.symbol} value={`${r.symbol} — ${r.name}`} />
          ))}
        </datalist>
      </form>
    </header>
  );
}
