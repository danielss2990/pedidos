import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth";
import Layout from "./components/Layout";
import CatalogPage from "./pages/CatalogPage";
import ConversationsPage from "./pages/ConversationsPage";
import LoginPage from "./pages/LoginPage";
import OrdersPage from "./pages/OrdersPage";
import SettingsPage from "./pages/SettingsPage";
import UsersPage from "./pages/UsersPage";

export default function App() {
  const { user, loading, can } = useAuth();

  if (loading) return <div className="splash">Carregando…</div>;
  if (!user) return <LoginPage />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/conversas" replace />} />
        <Route path="/conversas/:id?" element={<ConversationsPage />} />
        <Route path="/pedidos/:id?" element={<OrdersPage />} />
        <Route path="/catalogo" element={<CatalogPage />} />
        {can("admin") && <Route path="/configuracoes" element={<SettingsPage />} />}
        {can("admin") && <Route path="/usuarios" element={<UsersPage />} />}
        <Route path="*" element={<Navigate to="/conversas" replace />} />
      </Route>
    </Routes>
  );
}
