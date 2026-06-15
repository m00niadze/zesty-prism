import { NavLink, Outlet } from "react-router-dom";

const nav = [
  { to: "/", label: "Arbitrage" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/pnl", label: "PNL" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-8">
        <span className="text-brand font-bold text-lg tracking-tight">⚡ Zesty Prism</span>
        <nav className="flex gap-1">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        <Outlet />
      </main>
    </div>
  );
}
