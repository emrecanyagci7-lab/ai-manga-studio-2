import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Loader2, Compass, BookOpenText } from "lucide-react";
import { api, fileUrl } from "../lib/client";

export default function Explore() {
  const [mangas, setMangas] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/mangas/explore");
        setMangas(data.mangas || []);
      } catch { toast.error("Failed"); }
      finally { setLoading(false); }
    })();
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
      <div className="mb-10">
        <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2 flex items-center gap-2">
          <Compass className="w-3 h-3" /> // Community Feed
        </div>
        <h1 className="font-display text-5xl md:text-6xl tracking-widest uppercase">Explore</h1>
        <p className="mt-2 text-slate-400">Manga published by the community. Read anything, get inspired.</p>
      </div>

      {loading ? (
        <div className="flex justify-center py-24"><Loader2 className="w-8 h-8 animate-spin text-violet-400" /></div>
      ) : mangas.length === 0 ? (
        <div className="ink-card p-14 text-center">
          <Compass className="w-14 h-14 text-violet-400 mx-auto mb-4" />
          <div className="font-display text-3xl tracking-widest uppercase mb-3">Nothing Published Yet</div>
          <p className="text-slate-400">Be the first to publish your manga to the Explore feed.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6">
          {mangas.map((m, i) => (
            <motion.div key={m.id} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
              <Link to={`/manga/${m.id}`} data-testid={`explore-card-${m.id}`}>
                <div className="ink-card overflow-hidden hover:border-violet-500/40 hover:-translate-y-1 transition-transform group">
                  <div className="aspect-[2/3] bg-slate-900 halftone flex items-center justify-center">
                    {m.cover_url ? (
                      <img src={fileUrl(m.cover_url)} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <BookOpenText className="w-10 h-10 text-slate-600" />
                    )}
                  </div>
                  <div className="p-3">
                    <div className="font-display text-lg tracking-wide truncate group-hover:text-violet-300">{m.title}</div>
                    <div className="text-[10px] tracking-widest uppercase text-slate-500 mt-1">{m.genre}</div>
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
