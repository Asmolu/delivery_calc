/* eslint-disable react-refresh/only-export-components */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Home from "./pages/Home";
import Calculator from "./pages/Calculator";
import Admin from "./pages/Admin";
import Login from "./pages/Login";
import Orders from "./pages/Orders";
import AdminFactories from "./pages/AdminFactories";
import AdminTariffs from "./pages/AdminTariffs";
import AdminUsers from "./pages/AdminUsers";
import AdminVariantReport from "./pages/AdminVariantReport";
import InviteAccept from "./pages/InviteAccept";
import Layout from "./layouts/Layout";
import { isAuthenticated } from "./api";
import "./index.css";

function ProtectedRoute({ children }) {
  const location = useLocation();
  if (!isAuthenticated()) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/calculator" element={<Calculator />} />
        <Route path="/login" element={<Login />} />
        <Route path="/invite/:token" element={<InviteAccept />} />
        <Route path="/:token" element={<InviteAccept />} />
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
          path="/admin/users"
          element={
            <ProtectedRoute>
              <AdminUsers />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/reports/variants"
          element={
            <ProtectedRoute>
              <AdminVariantReport />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/reports/variants/"
          element={
            <ProtectedRoute>
              <AdminVariantReport />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/reports"
          element={
            <ProtectedRoute>
              <AdminVariantReport />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/reports/*"
          element={
            <ProtectedRoute>
              <AdminVariantReport />
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
