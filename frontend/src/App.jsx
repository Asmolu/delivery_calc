import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Calculator from "./pages/Calculator.jsx";
import Admin from "./pages/Admin.jsx";
import AdminUsers from "./pages/AdminUsers.jsx";
import Login from "./pages/Login.jsx";
import Orders from "./pages/Orders.jsx";
import InviteAccept from "./pages/InviteAccept.jsx";
import AdminVariantReport from "./pages/AdminVariantReport.jsx";
import { isAuthenticated } from "./api";

// Компонент для защиты маршрутов
function ProtectedRoute({ children }) {
  const location = useLocation();
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/calculator" element={<Calculator />} />
        <Route path="/login" element={<Login />} />
        <Route path="/invite/:token" element={<InviteAccept />} />
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <Admin />
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
      </Routes>
    </BrowserRouter>
  );
}
