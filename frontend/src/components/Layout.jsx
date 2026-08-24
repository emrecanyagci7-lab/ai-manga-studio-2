import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Home, Library, Compass, Plus, Settings as SettingsIcon } from "lucide-react";
import { Toaster } from "sonner";

const navItems = [
  { to: "/", label: "Home", icon: Home, testid: "nav-home" },
  { to: "/create", label: "Create", icon: Plus, testid: "nav-create" },
  { to: "/library", label: "Library", icon: Library, testid: "nav-library" },
  { to: "/explore", label: "Explore", icon: Compass, testid: "nav-explore" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "nav-settings" },
];

export default function Layout() {
  const loc = useLocation();
  const isReader = loc.pathname.includes("/read/");

  return (
    <div className="min-h-screen text-slate-100 pb-20 md:pb-0">
      {!isReader && (
        <header className="sticky top-0 z-40 backdrop-blur-2xl bg-slate-950/60 border-b border-white/10">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
            <Link to="/" data-testid="logo-link" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-md bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center font-display text-lg text-white">M</div>
              <span className="font-display text-2xl tracking-widest">MANGA<span className="text-violet-400">.STUDIO</span></span>
            </Link>
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map(({ to, label, icon: Icon, testid }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  data-testid={testid}
                  className={({ isActive }) =>
                    `px-4 py-2 rounded-lg text-sm tracking-wider uppercase font-medium flex items-center gap-2 hover:bg-white/5 transition-colors ${
                      isActive ? "text-violet-300 bg-white/5" : "text-slate-300"
                    }`
                  }
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>
      )}

      <main>
        <motion.div
          key={loc.pathname}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Outlet />
        </motion.div>
      </main>

      {!isReader && (
        <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 backdrop-blur-2xl bg-slate-950/80 border-t border-white/10">
          <div className="grid grid-cols-5">
            {navItems.map(({ to, label, icon: Icon, testid }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                data-testid={`${testid}-mobile`}
                className={({ isActive }) =>
                  `flex flex-col items-center justify-center py-3 gap-1 ${
                    isActive ? "text-violet-400" : "text-slate-400"
                  }`
                }
              >
                <Icon className="w-5 h-5" />
                <span className="text-[10px] tracking-widest uppercase">{label}</span>
              </NavLink>
            ))}
          </div>
        </nav>
      )}
      <Toaster theme="dark" position="top-right" richColors />
    </div>
  );
}
