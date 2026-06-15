import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ArbPage from "./pages/ArbPage";
import PnlPage from "./pages/PnlPage";
import PortfolioPage from "./pages/PortfolioPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ArbPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="pnl" element={<PnlPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
