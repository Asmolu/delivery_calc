import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";

export default function Home() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();

  const handleDemo = () => {
    sessionStorage.setItem("demo_coords", "55.616000, 37.387000");
    navigate("/calculator");
  };

  return (
    <MotionDiv
      className="space-y-10"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
    >
      <div className="card-glass grid md:grid-cols-[1.1fr_0.9fr] gap-10 p-8 md:p-10">
        <div className="space-y-6">
          <div className="pill w-fit">Новый дизайн • Подходит для десктопа и мобильных</div>
          <h1 className="text-4xl md:text-5xl font-bold leading-tight">
            Умный калькулятор доставки стройматериалов
          </h1>
          <p className="text-slate-600 text-lg leading-relaxed">
            DeliveryCalc сравнивает все заводы, тарифы и транспорт, чтобы предложить самый
            выгодный вариант доставки с учётом веса, расстояния и обязательного оборудования.
          </p>

          <div className="flex flex-col sm:flex-row gap-3">
            <Link
              to="/calculator"
              className="px-5 py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl shadow-md shadow-indigo-200 text-center"
            >
              🚀 Перейти к расчёту
            </Link>
            <Link
              to="/admin"
              className="px-5 py-3 bg-white border border-slate-200 text-slate-800 hover:border-indigo-200 rounded-xl font-semibold shadow"
            >
              ⚙️ Управление данными
            </Link>
            <button
              onClick={handleDemo}
              className="px-5 py-3 bg-amber-500 hover:bg-amber-400 text-black font-semibold rounded-xl shadow"
            >
              ⚡ Мини-демо координат
            </button>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-indigo-50 border border-indigo-100">
              <p className="text-xs uppercase tracking-wide text-indigo-700 font-semibold mb-2">
                Как это работает
              </p>
              <ul className="text-sm text-slate-700 space-y-2">
                <li>1. Укажите точку выгрузки (координаты).</li>
                <li>2. Выберите товары и их количество.</li>
                <li>3. Задайте тип транспорта или оставьте автоматический.</li>
                <li>4. Получите топ-3 сочетания с разбивкой по рейсам.</li>
              </ul>
            </div>
            <div className="p-4 rounded-xl bg-white border border-slate-200 shadow-sm grid-banner">
              <p className="text-xs uppercase tracking-wide text-slate-600 font-semibold mb-3">Быстрый пример</p>
              <p className="text-sm text-slate-700 leading-relaxed">
                Координаты: <code className="text-indigo-700">55.7558, 37.6173</code> • Категория: ФБС блоки • Подтип: ФБС 24-6-6 • Количество: 10
                <br />
                Нажмите «Перейти к расчёту» и увидите расстояние, подходящую машину, стоимость материала и доставки.
              </p>
            </div>
          </div>
        </div>

        <div className="card-glass bg-white/80 border border-slate-100 shadow-xl p-6 md:p-8 rounded-2xl">
          <div className="text-sm text-slate-500 mb-2">Превью интерфейса</div>
          <div className="rounded-xl border border-slate-200 overflow-hidden shadow-lg">
            <img
              src="https://placehold.co/900x600/ffffff/0f172a?text=DeliveryCalc+UI"
              alt="Макет интерфейса DeliveryCalc"
              className="w-full h-auto"
            />
          </div>
          <p className="text-sm text-slate-600 mt-3">
            Интерфейс адаптирован под телефоны и десктоп: таблицы с прокруткой, крупные кнопки и понятные отступы.
          </p>
        </div>
      </div>
    </MotionDiv>
  );
}
