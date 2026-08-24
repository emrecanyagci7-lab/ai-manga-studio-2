import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Plus, BookOpenText, Loader2 } from "lucide-react";
import { api, getClientId, fileUrl } from "../lib/client";
import { Button } from "../components/ui/button";

const GENRE_TR = {
  "Fantasy": "Fantezi", "Sci-Fi": "Bilim Kurgu", "Slice of Life": "Günlük Yaşam",
  "Action": "Aksiyon", "Romance": "Romantik", "Horror": "Korku",
  "Mystery": "Gizem", "Sports": "Spor", "Isekai": "Isekai",
};

export default function Library() {
  const [mangas, setMangas] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get("/mangas", { params: { client_id: getClientId() } });
        setMangas(data.mangas || []);
      } catch {
        toast.error("Kütüphane yüklenemedi");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
      <div className="flex items-end justify-between mb-10">
        <div>
          <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2">// Kasam</div>
          <h1 className="font-display text-5xl md:text-6xl tracking-widest uppercase">Mangaların</h1>
        </div>
        <Link to="/create">
          <Button data-testid="library-new-btn" className="bg-violet-600 hover:bg-violet-500 text-white uppercase tracking-widest">
            <Plus className="w-4 h-4 mr-2" /> Yeni
          </Button>
        </Link>
      </div>

      {loading ? (
        <div className="flex justify-center py-24"><Loader2 className="w-8 h-8 animate-spin text-violet-400" /></div>
      ) : mangas.length === 0 ? (
        <div className="ink-card p-14 text-center">
          <BookOpenText className="w-14 h-14 text-violet-400 mx-auto mb-4" />
          <div className="font-display text-3xl tracking-widest uppercase mb-3">Boş Stüdyo</div>
          <p className="text-slate-400 mb-6">İlk fikrini eskize dök, manga hayat bulsun.</p>
          <Link to="/create"><Button className="bg-violet-600 hover:bg-violet-500">Oluşturmaya Başla</Button></Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6">
          {mangas.map((m, i) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
            >
              <Link to={`/manga/${m.id}`} data-testid={`library-card-${m.id}`}>
                <div className="ink-card overflow-hidden hover:border-violet-500/40 hover:-translate-y-1 transition-transform group">
                  <div className="aspect-[2/3] bg-slate-900 halftone flex items-center justify-center relative">
                    {m.cover_url ? (
                      <img src={fileUrl(m.cover_url)} alt={m.title} className="w-full h-full object-cover" />
                    ) : (
                      <BookOpenText className="w-10 h-10 text-slate-600" />
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent" />
                    {m.is_published && (
                      <span className="absolute top-2 right-2 text-[9px] tracking-widest uppercase px-2 py-1 rounded bg-emerald-500/25 text-emerald-200">Yayında</span>
                    )}
                  </div>
                  <div className="p-3">
                    <div className="font-display text-lg tracking-wide truncate group-hover:text-violet-300">{m.title}</div>
                    <div className="text-[10px] tracking-widest uppercase text-slate-500 mt-1">{GENRE_TR[m.genre] || m.genre} · {m.chapter_count} böl</div>
                  </div>
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
