import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import HistoryPage from "./pages/History";
import PreviewPage from "./pages/Preview";
import SettingsModels from "./pages/SettingsModels";
import FormatPage from "./pages/Format";
import Home from "./pages/Home";
import Create from "./pages/Create";
import Polish from "./pages/Polish";
import Templates from "./pages/Templates";
import TopicPage from "./pages/create/TopicPage";
import AbstractPage from "./pages/create/AbstractPage";
import ReferencesPage from "./pages/create/ReferencesPage";
import OutlineReviewPage from "./pages/create/OutlineReviewPage";
import BodyPage from "./pages/create/BodyPage";
import VisualizationLab from "./pages/VisualizationLab";

function CreateIndexRedirect() {
  const location = useLocation();
  return (
    <Navigate
      to={{ pathname: "/create/topic", search: location.search }}
      replace
    />
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/create" element={<Create />}>
          <Route index element={<CreateIndexRedirect />} />
          <Route path="topic" element={<TopicPage />} />
          <Route path="abstract" element={<AbstractPage />} />
          <Route path="references" element={<ReferencesPage />} />
          <Route path="outline" element={<OutlineReviewPage />} />
          <Route path="body" element={<BodyPage />} />
        </Route>
        <Route path="/polish" element={<Polish />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings/models" element={<SettingsModels />} />
        <Route path="/format/:taskId" element={<FormatPage />} />
        <Route path="/preview/:taskId" element={<PreviewPage />} />
        <Route path="/lab/:taskId" element={<VisualizationLab />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
