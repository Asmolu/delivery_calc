import React from "react";
import { Link } from "react-router-dom";

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-neutral-900 to-neutral-950 text-gray-100 font-inter flex flex-col">
      <header className="border-b border-white/10 bg-white/5 backdrop-blur-md sticky top-0 z-50 shadow-lg shadow-black/30">
        <div className="max-w-6xl mx-auto flex justify-between items-center py-4 px-6">
          <Link to="/" className="text-2xl font-semibold tracking-tight text-white hover:text-blue-400 transition">
            🚚 DeliveryCalc
          </Link>
          <nav className="flex gap-6 text-sm">
            <Link to="/" className="hover:text-blue-400 transition">Главная</Link>
            <Link to="/calculator" className="hover:text-blue-400 transition">Калькулятор</Link>
            <Link to="/admin" className="hover:text-blue-400 transition">Управление данными</Link>
          </nav>
        </div>
      </header>


      {/* Content */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-6 py-10">{children}</main>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-4 text-center text-gray-500 text-sm">
        © {new Date().getFullYear()} DeliveryCalc 
      </footer>
    </div>
  );
}
