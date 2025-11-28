import React from "react";
import { Link } from "react-router-dom";

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-inter flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-xl sticky top-0 z-50 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="max-w-6xl mx-auto flex justify-between items-center py-4 px-4 md:px-6">
          <Link
            to="/"
            className="text-2xl font-semibold tracking-tight text-slate-50 hover:text-indigo-300 transition"
          >
            🚚 DeliveryCalc
          </Link>
          <nav className="flex gap-4 md:gap-6 text-sm font-medium text-slate-300">
            <Link to="/" className="hover:text-indigo-300 transition">
              Главная
            </Link>
            <Link to="/calculator" className="hover:text-indigo-300 transition">
              Калькулятор
            </Link>
            <Link to="/admin" className="hover:text-indigo-300 transition">
              Управление данными
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 md:px-8 py-10">{children}</main>


      <footer className="border-t border-slate-800 bg-slate-900/80 backdrop-blur text-center text-slate-400 text-sm py-4">
        © {new Date().getFullYear()} DeliveryCalc — расчёт доставки без головной боли
      </footer>
    </div>
  );
}
