"use client";

import Link from "next/link";

const SCOPES: Record<string, {
  status: string;
  title: string;
  detail: string;
  facts: [string, string][];
}> = {
  D: {
    status: "pending GPUs",
    title: "ZK proof (pending GPUs)",
    detail:
      "This path will be implemented when GPUs are added to Sunburst. Tachyon is the intended proving system for models up to 2.4B parameters. No proof or proving measurement is live yet.",
    facts: [
      ["deployment", "Sunburst GPU"],
      ["proving system", "Tachyon"],
      ["model size", "up to 2.4B parameters"],
      ["current claim", "none — pending hardware and measurements"],
    ],
  },
};

export function LegScope({ leg }: { leg: string }) {
  const scope = SCOPES[leg];
  if (!scope) return null;
  return (
    <div className="scope-body" id="leg-content">
      <main className="scope-state" aria-live="polite">
        <div className="scope-head">
          <div>
            <div className="eyebrow">inference option</div>
            <h1>{scope.title}</h1>
          </div>
          <div className="scope-status">{scope.status}</div>
        </div>
        <p>{scope.detail}</p>
        <dl className="scope-facts">
          {scope.facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <Link className="scope-action" href="/measurements/">
          view measurements
        </Link>
      </main>
    </div>
  );
}
