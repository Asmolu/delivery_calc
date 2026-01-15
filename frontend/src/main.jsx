/* eslint-disable react-refresh/only-export-components */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Home from "./pages/Home";
import Calculator from "./pages/Calculator";
import Admin from "./pages/Admin";
import Login from "./pages/Login";
import Orders from "./pages/Orders";
import AdminFactories from "./pages/AdminFactories";
import AdminTariffs from "./pages/AdminTariffs";
import Layout from "./layouts/Layout";
import { isAuthenticated } from "./api";
import "./index.css";

function ProtectedRoute({ children }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/calculator" element={<Calculator />} />
        <Route path="/login" element={<Login />} />
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <Admin />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/factories"
          element={
            <ProtectedRoute>
              <AdminFactories />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/tariffs"
          element={
            <ProtectedRoute>
              <AdminTariffs />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/orders"
          element={
            <ProtectedRoute>
              <Orders />
            </ProtectedRoute>
          }
        />
        <Route
          path="/orders"
          element={
            <ProtectedRoute>
              <Orders />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  </BrowserRouter>
);
