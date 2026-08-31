const TABS = [
  {
    id: "pull",
    label: "Menu Pull",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
    ),
  },
  {
    id: "push",
    label: "Menu Push",
    badge: "C5",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
      </svg>
    ),
  },

  {
    id: "edit-harga",
    label: "Edit Harga",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: "shopee-edit-harga",
    label: "Edit Harga",
    badge: "Shopee",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 11V7a4 4 0 00-8 0v4M5 11h14a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2z" />
      </svg>
    ),
  },
  {
    id: "session",
    label: "Sesi",
    badge: "Shopee",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
      </svg>
    ),
  },
];

export default function NavHeader({ activeTab, onTabChange, theme, onToggleTheme }) {
  return (
    <header className="sticky top-0 z-50 border-b border-red-100 bg-white/95 shadow-[0_8px_30px_-20px_rgba(127,29,29,0.45)] backdrop-blur-xl dark:border-white/5 dark:bg-black/20 dark:shadow-none dark:backdrop-blur-md">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between py-3.5 sm:py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-red-600 to-red-800 shadow-lg shadow-red-900/20 dark:from-zinc-800 dark:to-zinc-950 dark:border dark:border-zinc-700 dark:shadow-none">
              <svg className="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M8.1 13.34l2.83-2.83L3.91 3.5a4.008 4.008 0 000 5.66l4.19 4.18zm6.78-1.81c1.53.71 3.68.21 5.27-1.38 1.91-1.91 2.28-4.65.81-6.12-1.46-1.46-4.2-1.1-6.12.81-1.59 1.59-2.09 3.74-1.38 5.27L3.7 19.87l1.41 1.41L12 14.41l6.88 6.88 1.41-1.41L13.41 13l1.47-1.47z" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold leading-tight tracking-tight text-slate-900 dark:text-white sm:text-lg">
                FoodMaster
              </h1>
              <p className="mt-0.5 hidden text-[13px] text-slate-500 dark:text-zinc-400 sm:block">
                Unified menu operations
              </p>
            </div>
          </div>

          {/* Theme Toggle Button */}
          <button
            type="button"
            onClick={onToggleTheme}
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-100 hover:text-slate-900 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 dark:hover:text-white"
            title={theme === "dark" ? "Beralih ke Mode Terang (Light Mode)" : "Beralih ke Mode Gelap (Dark Mode)"}
          >
            {theme === "dark" ? (
              <>
                <svg className="h-4 w-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                <span className="hidden sm:inline">Light Mode</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4 text-slate-600 dark:text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
                <span className="hidden sm:inline">Dark Mode</span>
              </>
            )}
          </button>
        </div>

        <nav className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-3 sm:mx-0 sm:px-0" aria-label="Menu utama">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const isShopee = tab.id === "shopee-edit-harga" || tab.id === "session";

            let activeClasses = "";
            if (isActive) {
              if (isShopee) {
                activeClasses = "bg-orange-600 text-white shadow-md shadow-orange-950/20 dark:bg-orange-600 dark:text-white dark:shadow-lg dark:shadow-orange-950/50";
              } else {
                activeClasses = "bg-red-700 text-white shadow-md shadow-red-950/20 dark:bg-zinc-800 dark:text-white dark:border dark:border-zinc-700 dark:shadow-none";
              }
            } else {
              activeClasses = "text-slate-600 hover:bg-red-50 hover:text-red-700 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-white";
            }

            return (
              <button
                type="button"
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                aria-current={isActive ? "page" : undefined}
                className={`group relative flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-[15px] font-semibold transition-all ${activeClasses}`}
              >
                <span className={isActive ? "text-white" : "text-slate-400 group-hover:text-red-600 dark:text-zinc-500 dark:group-hover:text-white"}>
                  {tab.icon}
                </span>
                {tab.label}
                {tab.badge && (
                  <span className={isActive ? "rounded-full bg-white/20 px-1.5 py-0.5 text-[11px] text-white" : "rounded-full bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600 dark:bg-zinc-800 dark:text-zinc-300"}>
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
