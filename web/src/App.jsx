import { useState } from "react";
import NavHeader from "./components/NavHeader";
import MenuPullTab from "./components/MenuPullTab";
import MenuPushTab from "./components/MenuPushTab";
import EditHargaTab from "./components/EditHargaTab";
import ShopeeEditHargaTab from "./components/ShopeeEditHargaTab";
import SessionTab from "./components/SessionTab";
import StarField from "./components/StarField";
import { useTheme } from "./hooks/useTheme";

export default function Home() {
  const { theme, toggleTheme } = useTheme();
  const [activeTab, setActiveTab] = useState(() => {
    const isSessionPath = window.location.pathname === "/session";
    const requestedTab = new URLSearchParams(window.location.search).get("tab");
    if (isSessionPath || requestedTab === "session") {
      return "session";
    }
    return ["pull", "push", "edit-harga", "shopee-edit-harga"].includes(requestedTab) ? requestedTab : "pull";
  });
  const getApiBaseUrl = () => {
    if (import.meta.env.VITE_API_URL) {
      return import.meta.env.VITE_API_URL.replace(/\/+$/, "");
    }
    if (typeof window !== "undefined") {
      if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
        return "http://localhost:18800";
      }
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return "http://localhost:18800";
  };
  const API_BASE_URL = getApiBaseUrl();
  const API_SECRET_KEY = import.meta.env.VITE_API_KEY || "foodmaster-secret-api-key-2026";

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    if (url.pathname === "/session") {
      url.pathname = "/";
    }
    if (tab === "pull") url.searchParams.delete("tab");
    else url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", url);
  };

  return (
    <div className="min-h-screen bg-[#fff9f8] text-slate-900 dark:bg-black dark:text-white transition-colors duration-200">
      <StarField active={theme === "dark"} />
      <NavHeader activeTab={activeTab} onTabChange={handleTabChange} theme={theme} onToggleTheme={toggleTheme} />

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className={activeTab === "pull" ? "" : "hidden"}><MenuPullTab API_BASE_URL={API_BASE_URL} API_SECRET_KEY={API_SECRET_KEY} /></div>
        <div className={activeTab === "push" ? "" : "hidden"}><MenuPushTab API_BASE_URL={API_BASE_URL} API_SECRET_KEY={API_SECRET_KEY} /></div>
        <div className={activeTab === "edit-harga" ? "" : "hidden"}><EditHargaTab API_BASE_URL={API_BASE_URL} API_SECRET_KEY={API_SECRET_KEY} /></div>
        <div className={activeTab === "shopee-edit-harga" ? "" : "hidden"}><ShopeeEditHargaTab API_BASE_URL={API_BASE_URL} API_SECRET_KEY={API_SECRET_KEY} /></div>
        <div className={activeTab === "session" ? "" : "hidden"}><SessionTab API_BASE_URL={API_BASE_URL} API_SECRET_KEY={API_SECRET_KEY} /></div>
      </main>
    </div>
  );
}
