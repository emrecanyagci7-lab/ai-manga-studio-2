import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import Create from "./pages/Create";
import Library from "./pages/Library";
import Explore from "./pages/Explore";
import Settings from "./pages/Settings";
import MangaDetail from "./pages/MangaDetail";
import Reader from "./pages/Reader";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/create" element={<Create />} />
          <Route path="/library" element={<Library />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/manga/:id" element={<MangaDetail />} />
          <Route path="/read/:mangaId/:chapterId" element={<Reader />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
