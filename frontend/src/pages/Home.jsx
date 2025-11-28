import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";

export default function Home() {
  const navigate = useNavigate();

  const handleDemo = () => {
    // Сохраняем демо-координаты в sessionStorage
    sessionStorage.setItem("demo_coords", "55.616000, 37.387000");
    navigate("/calculator");
  };

  return (
    <motion.div
      className="min-h-screen bg-gradient-to-b from-neutral-900 to-neutral-950 text-gray-100 flex flex-col items-center justify-center px-6 py-10"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
    >
      <div className="text-center max-w-3xl card-glass p-10 rounded-2xl shadow-lg">
        <h1 className="text-5xl font-bold mb-4 text-white tracking-tight">
          🚚 DeliveryCalc
        </h1>

        <p className="text-gray-300 text-lg mb-6 leading-relaxed">
          Умный калькулятор для расчёта стоимости доставки стройматериалов.
          <br />
          Введите координаты выгрузки, выберите категорию и подтип товара —
          система рассчитает оптимальный маршрут и итоговую сумму.
        </p>

        {/* Пример использования */}
        <div className="text-left text-gray-400 bg-gray-800/40 rounded-xl p-6 mb-8">
          <h2 className="text-xl font-semibold text-white mb-3">
            📘 Пример использования:
          </h2>
          <ul className="space-y-2 list-disc list-inside">
            <li>Введите координаты выгрузки (например: <code>55.7558, 37.6173</code>)</li>
            <li>Выберите категорию, например <strong>ФБС блоки</strong></li>
            <li>Выберите подтип — <strong>ФБС 24-6-6</strong></li>
            <li>Укажите количество</li>
            <li>Нажмите <strong>“Рассчитать стоимость”</strong></li>
          </ul>
          <p className="mt-4 text-sm text-gray-500">
            Результат покажет: расстояние, подходящую машину, цену материала и стоимость доставки.
          </p>
        </div>

        {/* 🔹 Демо блок */}
        <div className="bg-blue-900/30 border border-blue-700/40 rounded-xl p-6 mb-8">
          <h3 className="text-xl font-semibold mb-2 text-blue-300">
            ⚡ Мини-демо
          </h3>
          <p className="text-gray-300 mb-4">
            Нажмите кнопку ниже — координаты выгрузки <code>55.616000, 37.387000 </code> 
            будут подставлены автоматически.
          </p>
          <button
            onClick={handleDemo}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-xl font-semibold shadow-lg shadow-blue-500/30"
          >
            🚀 Попробовать
          </button>
        </div>

        {/* Кнопки перехода */}
        <div className="flex flex-col md:flex-row justify-center gap-4">
          <Link
            to="/calculator"
            className="px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-xl font-semibold shadow-lg shadow-blue-500/30"
          >
            🔢 Перейти к калькулятору
          </Link>
          <Link
            to="/admin"
            className="px-6 py-3 bg-green-600 hover:bg-green-500 rounded-xl font-semibold shadow-lg shadow-green-500/30"
          >
            ⚙️ Управление данными
          </Link>
        </div>
      </div>

      <p className="mt-10 text-gray-500 text-sm">
        © {new Date().getFullYear()} DeliveryCalc — точность, автоматизация, комфорт.
      </p>
    </motion.div>
  );
}
