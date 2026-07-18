import Link from "next/link";

const NAV_ITEMS = [
  { id: "console", href: "/", label: "console" },
  { id: "measurements", href: "/measurements/", label: "measurements" },
  { id: "how-it-works", href: "/how-it-works/", label: "how it works" },
] as const;

export function Masthead({
  active,
  detail,
}: {
  active: (typeof NAV_ITEMS)[number]["id"];
  detail?: string;
}) {
  return (
    <header className="masthead">
      <div className="wordmark">verified inference</div>
      <nav className="masthead-nav" aria-label="Views">
        {NAV_ITEMS.map((item) =>
          item.id === active ? (
            <span aria-current="page" key={item.id}>{item.label}</span>
          ) : (
            <Link href={item.href} key={item.id}>{item.label}</Link>
          ),
        )}
      </nav>
      {detail && <div className="masthead-endpoint">{detail}</div>}
    </header>
  );
}
